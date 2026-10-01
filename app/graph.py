from typing import TypedDict#, Annotated
import os
import asyncio
import json

from app.models import SearchFlights, BookFlight
from app.tools import (
    TOOL_HANDLERS, 
    fetch_flight_details,
    search_flights_tool,
    book_flight_tool,
    get_saved_passengers_tool
    )
from app.core.errors import (
    ToolNotFound, 
    AppError, 
    FlightNotFound,
    UpstreamTimeout,
    UpstreamRateLimited,
    UpstreamUnavailable,
    InvalidUpstreamResponse
)
from app.core.rate_limiter import llm_rate_limiter

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import StateGraph, START, END
# from langgraph.graph.message import add_messages
from langgraph.types import interrupt, Command
from openai import AsyncOpenAI, APITimeoutError, RateLimitError, APIConnectionError
from dotenv import load_dotenv


MAX_REQUESTS = 5
MAX_SECONDS = 1

load_dotenv()
llm_semaphore = asyncio.Semaphore(3)

client = AsyncOpenAI(
    api_key=os.getenv("LLM_API_KEY"),
)

class AgentState(TypedDict):
    messages: list
    
async def call_tool_with(tool_call, arguments, flight=None):
    tool_name = tool_call["function"]["name"]
    
    handler = TOOL_HANDLERS.get(tool_name)
    if handler is None:
        raise ToolNotFound(f"Unknown tool: {tool_name}")
    
    if tool_name == "book_flight":
        return await handler(arguments, flight)
    return await handler(arguments)
    
    
async def call_llm(state: AgentState):
    try:
        await llm_rate_limiter.acquire()
        async with llm_semaphore:
            response = await client.chat.completions.create(
                model=os.getenv("LLM_MODEL"),
                messages=state["messages"],
                tools=[
                    {
                        "type": "function",
                        "function": search_flights_tool
                    },
                    {
                        "type": "function",
                        "function": book_flight_tool
                    },
                    {
                        "type": "function",
                        "function": get_saved_passengers_tool
                    }
                ]
            )
        
        if not response.choices:
            raise InvalidUpstreamResponse("LLM provider returned an empty response.")
            
    except APITimeoutError as exc:
        raise UpstreamTimeout("LLM request timed out.") from exc
    except RateLimitError as exc:
        raise UpstreamRateLimited("LLM rate limit exceeded.") from exc
    except APIConnectionError as exc:
        raise UpstreamUnavailable("LLM provider currently unavailable.") from exc
    
    return {
        "messages": [
            *state["messages"],
            response.choices[0].message.model_dump()
        ]
    }
    
async def execute_tools(state: AgentState):
    last_message = state["messages"][-1]
    
    tool_messages = []
    for tool_call in last_message["tool_calls"]:
        print("Tool name: ", tool_call["function"]["name"])
        
        flight = None
        
        try:
            arguments = json.loads(tool_call["function"]["arguments"])
            
            if tool_call["function"]["name"] == "book_flight":
                flight = await fetch_flight_details(arguments["flight_id"])
                            
                if flight is None:
                    raise FlightNotFound(f"Flight {arguments['flight_id']} not found.")
                
                message = (
                    f"I found {flight.flight_name} from "
                    f"{flight.origin.airport_code} to {flight.destination.airport_code}. "
                    f"Departure: {flight.departure_datetime}. "
                    f"Arrival: {flight.arrival_datetime}. "
                    f"Price: {flight.price} {flight.currency} total. "
                    f"Passengers: {len(arguments['passenger_ids'])}. "
                    f"Would you like me to proceed with the booking?"
                )
                approval = interrupt({
                    "type": "approval_required",
                    "message": message,
                    "tool": "book_flight",
                    "arguments": arguments,
                    "flight": flight.model_dump(mode="json") if flight else None,
                })
                
                if approval.lower() != "yes":
                    print("Booking rejected by user.")
                    
                    tool_messages.append({
                        "role": "tool",
                        "tool_call_id": tool_call["id"],
                        "content": "The user rejected the booking. Do not book the flight."
                    })
                    continue
        
        
            result = await call_tool_with(tool_call, arguments, flight)
        except json.JSONDecodeError:
            result = json.dumps({
                "error": (
                    f"Invalid JSON arguments for tool "
                    f"'{tool_call['function']['name']}'."
                )
            })
            
        except AppError as exc:
            result = json.dumps({
                "error": str(exc)
            })
        tool_messages.append({
            "role": "tool",
            "tool_call_id": tool_call["id"],
            "content": result
        })
    return {
        "messages": [
            *state["messages"],
            *tool_messages
        ]
    }
    

async def safe_call_llm(state: AgentState):
    try:
        return await call_llm(state)
    except UpstreamTimeout:
        return {
            "messages": [
                *state["messages"],
                {
                    "role": "assistant",
                    "content": (
                        "I'm sorry, but the flight service is temporarily unavailable. "
                        "Please try again."
                    ),
                }
            ]
        }
    except UpstreamRateLimited:
        return {
            "messages": [
                *state["messages"],
                {
                    "role": "assistant",
                    "content": (
                        "The AI service is currently receiving too many "
                        "requests. Please try again shortly."
                    ),
                }
            ]
        }
    except UpstreamUnavailable:
        return {
            "messages": [
                *state["messages"],
                {
                    "role": "assistant",
                    "content": (
                        "The AI service is currently unavailable. "
                        "Please try again shortly."
                    ),
                },
            ]
        }
    except InvalidUpstreamResponse:
        return {
            "messages": [
                *state["messages"],
                {
                    "role": "assistant",
                    "content": (
                        "I received an invalid response from the AI service. "
                        "Please try again."
                    ),
                },
            ]
        }
    
def route_after_llm(state: AgentState):
    last_message = state["messages"][-1]
    
    if last_message.get("tool_calls"):
        return "tools"
    return END
    
checkpointer = InMemorySaver()
builder = StateGraph(AgentState)

builder.add_node("llm", safe_call_llm)
builder.add_node("tools", execute_tools)

builder.add_edge(START, "llm")
builder.add_conditional_edges(
    "llm",
    route_after_llm,
    {
        "tools": "tools",
        END: END
    }
)
builder.add_edge("tools", "llm")

graph = builder.compile(checkpointer=checkpointer)


async def main():
    config = {
        "configurable": {
            "thread_id": "booking-001"
        }
    }
    result = await graph.ainvoke(
        {
            "messages": [
                {
                    "role": "user",
                    "content": "Find economy flights from DEL to DXB for 2 passengers on 2026-10-02 and book the cheapest one. Also provide me comparison for prices for different flights"
                }
            ]
        },
        config=config
    )
    
    interrupts = result.get("__interrupt__")
    
    if interrupts:
        interrupt_data = result["__interrupt__"][0]
        print(interrupt_data.value["message"])
        approval = input("Your response: ")
        
        result = await graph.ainvoke(
            Command(resume=approval),
            config=config
        )

    print(result["messages"][-1].get("content"))

if __name__ == "__main__":
    asyncio.run(main())
    
