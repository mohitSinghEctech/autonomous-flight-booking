import json

import httpx
from langgraph.types import interrupt

from app.agent.handlers import parse_arguments
from app.agent.state import AgentState
from app.core.errors import AppError, FlightNotFound
from app.models import BookFlight
from app.providers.all_providers import flight_provider


async def request_booking_approval(tool_call: dict) -> bool:
    """Show the user what will be booked and pause until they answer."""

    request = parse_arguments(tool_call, BookFlight)

    flight = await flight_provider.fetch_flight_details(request.flight_id)

    if flight is None:
        raise FlightNotFound(f"Flight {request.flight_id} not found.")

    message = (
        f"I found {flight.flight_name} from "
        f"{flight.origin.airport_code} "
        f"to {flight.destination.airport_code}. "
        f"Departure: {flight.departure_datetime}. "
        f"Arrival: {flight.arrival_datetime}. "
        f"Price: {flight.price} {flight.currency} total. "
        f"Passengers: {len(request.passenger_ids)}. "
        f"Would you like me to proceed with the booking?"
    )

    # Pauses the graph. On resume, LangGraph re-runs this node from the top
    # and interrupt() returns the value passed in Command(resume=...).
    answer = interrupt({
        "type": "approval_required",
        "message": message,
        "tool": "book_flight",
        "arguments": request.model_dump(mode="json"),
        "flight": flight.model_dump(mode="json"),
    })

    return str(answer).strip().lower() in {"yes", "y"}


async def approval_node(state: AgentState):
    """
    Approved -> no change; the router sends us on to the tools node.
    Declined -> answer every tool call so the LLM sees why nothing ran.
    """

    tool_calls = state["messages"][-1]["tool_calls"]

    for tool_call in tool_calls:
        if tool_call["function"]["name"] != "book_flight":
            continue

        try:
            approved = await request_booking_approval(tool_call)
        except (AppError, httpx.HTTPError) as exc:
            return skip_tool_calls(tool_calls, f"Could not prepare booking: {exc}")

        if not approved:
            return skip_tool_calls(tool_calls, "The user declined the booking.")

    return {}


def skip_tool_calls(tool_calls: list[dict], reason: str):
    return {
        "messages": [
            {
                "role": "tool",
                "tool_call_id": tool_call["id"],
                "content": json.dumps({"error": reason}),
            }
            for tool_call in tool_calls
        ]
    }
