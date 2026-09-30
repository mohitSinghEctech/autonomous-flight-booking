from typing import TypedDict#, Annotated
import os
import asyncio
import json

from app.models import SearchFlights, BookFlight
from app.tools import TOOL_HANDLERS, get_flight

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import StateGraph, START, END
# from langgraph.graph.message import add_messages
from langgraph.types import interrupt, Command
from openai import AsyncOpenAI
from dotenv import load_dotenv

load_dotenv()


# Tools
search_flights_tool = {
    "name": "search_flights",
    "description": (
        "Search for available flights. "
        "origin and destination must be IATA airport codes, "
        "such as DEL for Delhi and DXB for Dubai."
    ),
    "parameters": SearchFlights.model_json_schema(),
}

book_flight_tool = {
    "name": "book_flight",
    "description": (
        "Book a selected flight. "
        "flight_id must be the exact flight_id returned by search_flights."
    ),
    "parameters": BookFlight.model_json_schema(),
}


client = AsyncOpenAI(
    api_key=os.getenv("LLM_API_KEY")
)

class AgentState(TypedDict):
    messages: list
    
def call_tool_with(tool_call):
    tool_name = tool_call["function"]["name"]
    
    handler = TOOL_HANDLERS[tool_name]
    arguments = json.loads(tool_call["function"]["arguments"])
    result = handler(arguments)
    return result
    
    
async def call_llm(state: AgentState):
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
            }
        ]
    )
    
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
        
        arguments = json.loads(tool_call["function"]["arguments"])
        flight = get_flight(arguments["flight_id"])
        
        if tool_call["function"]["name"] == "book_flight":
            message = (
                f"I found {flight.flight_name} from "
                f"{flight.origin.airport_code} to {flight.destination.airport_code}. "
                f"Departure: {flight.departure_datetime}. "
                f"Arrival: {flight.arrival_datetime}. "
                f"Price: {flight.price} {flight.currency} per passenger. "
                f"Passengers: {arguments['passengers']}. "
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
        
        result = call_tool_with(tool_call)
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
    
def route_after_llm(state: AgentState):
    last_message = state["messages"][-1]
    
    if last_message["tool_calls"]:
        return "tools"
    return END
    
checkpointer = InMemorySaver()
builder = StateGraph(AgentState)

builder.add_node("llm", call_llm)
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
                    "content": "Book flight AI1000 from Delhi to Dubai for 2 passengers."
                }
            ]
        },
        config=config
    )
    
    interrupt_data = result["__interrupt__"][0]
    print(interrupt_data.value["message"])
    approval = input("Your response: ")
    
    result = await graph.ainvoke(
        Command(resume=approval),
        config=config
    )

    print(result)
    
if __name__ == "__main__":
    asyncio.run(main())