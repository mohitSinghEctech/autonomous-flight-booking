import json

import httpx
from langchain_core.runnables import RunnableConfig
from langgraph.types import interrupt

from app.agent.handlers import parse_arguments
from app.agent.state import AgentState
from app.api.event_bus import event_bus
from app.api.events import SSEEvent
from app.core.errors import AppError, FlightNotFound
from app.models import BookFlight
from app.providers.all_providers import flight_provider


async def request_booking_approval(
    tool_call: dict,
    thread_id: str,
) -> bool:

    request = parse_arguments(
        tool_call,
        BookFlight,
    )

    flight = await flight_provider.fetch_flight_details(
        request.flight_id
    )

    if flight is None:
        raise FlightNotFound(
            f"Flight {request.flight_id} not found."
        )

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

    approval_data = {
        "type": "approval_required",
        "message": message,
        "tool": "book_flight",
        "arguments": request.model_dump(mode="json"),
        "flight": flight.model_dump(mode="json"),
    }

    # The runner publishes approval.required from this value when the graph
    # pauses. Publishing it here would send it twice: on resume LangGraph
    # re-runs this whole node, and interrupt() only then returns the answer.
    answer = interrupt(approval_data)

    approved = (
        str(answer)
        .strip()
        .lower()
        in {"yes", "y", "true", "approve", "approved"}
    )

    await event_bus.publish(
        thread_id,
        SSEEvent(
            event="approval.resolved",
            data={
                "approved": approved,
            },
        ),
    )

    return approved


async def approval_node(state: AgentState, config: RunnableConfig):

    tool_calls = state["messages"][-1]["tool_calls"]

    # thread_id is not part of the state (LangGraph drops undeclared keys);
    # it arrives in the config the runner passes to ainvoke.
    thread_id = config["configurable"]["thread_id"]

    for tool_call in tool_calls:

        if tool_call["function"]["name"] != "book_flight":
            continue

        try:

            approved = await request_booking_approval(
                tool_call,
                thread_id,
            )

        except (
            AppError,
            httpx.HTTPError,
        ) as exc:

            return skip_tool_calls(
                tool_calls,
                f"Could not prepare booking: {exc}",
            )

        if not approved:

            return skip_tool_calls(
                tool_calls,
                "The user declined the booking.",
            )

    return {}


def skip_tool_calls(
    tool_calls: list[dict],
    reason: str,
):

    return {
        "messages": [
            {
                "role": "tool",
                "tool_call_id": tool_call["id"],
                "content": json.dumps(
                    {
                        "error": reason,
                    }
                ),
            }
            for tool_call in tool_calls
        ]
    }