from typing import TypedDict#, Annotated
import os
import asyncio
import json

from app.models import Booking, BookingLifecycle
from app.tools import (
    TOOL_HANDLERS, 
    fetch_flight_details,
    search_flights_tool,
    book_flight_tool,
    get_saved_passengers_tool,
    create_payment_tool,
    complete_payment_tool
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
    booking: dict | None
    payment: dict | None
    
async def call_tool_with(
    tool_call, 
    arguments, 
    flight=None, 
    booking=None,
    payment=None
    ):
    tool_name = tool_call["function"]["name"]
    
    handler = TOOL_HANDLERS.get(tool_name)
    if handler is None:
        raise ToolNotFound(f"Unknown tool: {tool_name}")
    
    if tool_name == "book_flight":
        return await handler(arguments, flight)
    
    if tool_name == "create_payment":
        return await handler(booking)
    
    if tool_name == "complete_payment":
        return await handler(payment)
    
    return await handler(arguments)
    
    
async def call_llm(state: AgentState):
    try:
        await llm_rate_limiter.acquire()
        
        messages = list(state["messages"])
        
        booking = state.get("booking")
        payment = state.get("payment")
        payment_status = None
        
        if payment:
            payment_status = payment.get("status")
        
        if booking:
            booking = Booking.model_validate(booking)
            messages.insert(
                0,
                {
                    "role": "system",
                    "content": (
                        f"Application booking state: {booking.lifecycle.value}. "
                        f"Application payment state: {payment_status or 'none'}. "

                        "If the booking lifecycle is HELD and the user wants to start "
                        "payment, call create_payment. "

                        "If the payment status is CREATED and the user wants to complete "
                        "the payment, call complete_payment. "

                        "Do not ask the user for booking ID, payment ID, amount, or currency. "
                        "The application provides those values."
                    ),
                },
            )
        
        async with llm_semaphore:
            response = await client.chat.completions.create(
                model=os.getenv("LLM_MODEL"),
                messages=messages,
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
                    },
                    {
                        "type": "function",
                        "function": create_payment_tool
                    },
                    {
                        "type": "function",
                        "function": complete_payment_tool
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
    booking = state.get("booking")
    payment = state.get("payment")
    if booking is not None:
        booking = Booking.model_validate(booking)
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
        
        
            result = await call_tool_with(tool_call, arguments, flight, booking, payment)
            
            if tool_call["function"]["name"] == "book_flight":
                booking_model = Booking.model_validate_json(result)
                booking = booking_model.model_dump(mode="json")
                
            elif tool_call["function"]["name"] == "create_payment":
                payment = json.loads(result)
                booking_model = Booking.model_validate(booking)
                booking_model.lifecycle = BookingLifecycle.AWAITING_PAYMENT
                booking = booking_model.model_dump(mode="json")
                
            elif tool_call["function"]["name"] == "complete_payment":
                payment = json.loads(result)

                if payment["status"] == "paid":
                    booking_model = Booking.model_validate(booking)
                    booking_model.lifecycle = BookingLifecycle.CONFIRMED
                    booking = booking_model.model_dump(mode="json")
            
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
        ],
        "booking": booking,
        "payment": payment
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

def print_state(label: str, result: dict):
    print(f"\n{'=' * 20} {label} {'=' * 20}")

    print("\nBooking:")
    print(result.get("booking"))

    print("\nPayment:")
    print(result.get("payment"))

    print()
    

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
                    "content": "Find economy flights from DEL to DXB for 2 passengers on 2026-10-10 and book the cheapest one. Also provide me comparison for prices for different flights"
                }
            ]
        },
        config=config
    )
    
    interrupts = result.get("__interrupt__")
    
    if interrupts:
        interrupt_data = result["__interrupt__"][0]
        print(interrupt_data.value["message"])
        approval = input("Your response (yes/no): ")
        
        result = await graph.ainvoke(
            Command(resume=approval),
            config=config
        )
        
    print_state("BOOKING CREATED", result)
    
    result = await graph.ainvoke(
        {
            "messages": [
                {
                    "role": "user",
                    "content": "Create the payment for my booking."
                }
            ]
        },
        config=config
    )

    print_state("PAYMENT CREATED", result)
    
    result = await graph.ainvoke(
        {
            "messages": [
                {
                    "role": "user",
                    "content": "Complete the payment for my booking."
                }
            ]
        },
        config=config
    )

    print_state("PAYMENT COMPLETED", result)

    print(result["messages"][-1].get("content"))
    
    print("\nFinal booking state:")
    print(result.get("booking"))

if __name__ == "__main__":
    asyncio.run(main())
    
