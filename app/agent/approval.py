import json
import uuid

import httpx
from langgraph.types import interrupt

from app.agent.handlers import parse_arguments
from app.agent.state import AgentState
from app.api.views import flight_view, passenger_view
from app.core.errors import AppError, FlightNotFound
from app.db.session import SessionLocal
from app.models import BookFlight
from app.providers import all_providers
from app.services.booking import BookingService


SUPERSEDED_REPLY = "Okay, I've set that aside."


async def build_booking_approval(tool_call: dict, state: AgentState) -> dict:
    """
    Everything the user needs to decide, in contract shape (ApprovalRequiredEvent).

    approval_id comes from the tool call id, so it is the SAME when LangGraph
    re-runs this node on resume — the API checks the user's answer against it.
    """
    request = parse_arguments(tool_call, BookFlight)

    # live price: offers change, and we never book at a price the user didn't see
    flight = await all_providers.flight_provider.fetch_flight_details(request.flight_id)

    if flight is None:
        raise FlightNotFound(f"Flight {request.flight_id} not found.")

    async with SessionLocal() as session:
        passengers = await BookingService(session).passenger_repository.get_passengers_by_ids(
            [uuid.UUID(pid) for pid in request.passenger_ids]
        )

    held = (state.get("booking") or {}).get("lifecycle") in ("held", "awaiting_payment")
    kind = "change" if held else "book"

    return {
        "approval_id": f"ap_{tool_call['id']}",
        "kind": kind,
        "flight_id": flight.flight_id,
        "flight": flight_view(flight),
        "passengers": [passenger_view(p) for p in passengers],
        "total_amount": flight.price,
        "currency": flight.currency,
        "message": (
            f"{'Switch to' if kind == 'change' else 'Hold'} {flight.flight_name} "
            f"{flight.origin.airport_code} → {flight.destination.airport_code} "
            f"for {flight.price:.2f} {flight.currency}?"
        ),
    }


async def approval_node(state: AgentState):
    """
    Pauses before book_flight runs. interrupt() hands the approval to the runner
    (which publishes approval.required) and, on resume, returns the decision:
    "approved" | "rejected" | "superseded".
    """
    tool_calls = state["messages"][-1]["tool_calls"]

    for tool_call in tool_calls:

        if tool_call["function"]["name"] != "book_flight":
            continue

        flight_id = json.loads(tool_call["function"]["arguments"] or "{}").get("flight_id")
        if flight_id in (state.get("unavailable_offers") or []):
            return skip_tool_calls(
                tool_calls,
                "This fare is no longer available. Do not retry it; search again for current fares.",
            )

        try:
            approval = await build_booking_approval(tool_call, state)

        except (AppError, httpx.HTTPError) as exc:
            return skip_tool_calls(tool_calls, f"Could not prepare booking: {exc}")

        decision = interrupt({"type": "approval", "approval": approval})

        if decision == "approved":
            continue

        if decision == "superseded":
            return supersede(tool_calls, "The user moved on to a different request.")

        return skip_tool_calls(tool_calls, "The user declined the booking.")

    return {}


def skip_tool_calls(
    tool_calls: list[dict],
    reason: str,
):
    """Every tool call must get a tool reply, or the next LLM call is rejected."""

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


def supersede(tool_calls: list[dict], reason: str):
    """Close the paused request quietly: tool replies + a short assistant line -> END."""

    result = skip_tool_calls(tool_calls, reason)
    result["messages"].append({"role": "assistant", "content": SUPERSEDED_REPLY})

    return result
