"""
Handlers translate an LLM tool call into one application operation.

Each one: parse arguments -> call a service/provider -> return a ToolResult.
Business rules live in the services, not here.

A ToolResult carries three things:
  content -> the tool message the LLM reads
  update  -> AgentState changes (booking, payment, db_booking_id)
  events  -> contract events for the browser (tools.py publishes them)
"""
import json
import uuid
from typing import Any, NamedTuple

from pydantic import BaseModel, ValidationError

from app.api.views import booking_view, flight_view, passenger_view, payment_view
from app.core.errors import AppError, InvalidToolArguments, InvalidUpstreamResponse
from app.db import models as db
from app.db.session import SessionLocal
from app.mcp.client import FlightMCPClient
from app.models import (
    BookFlight,
    Booking,
    BookingLifecycle,
    Flight,
    PaymentResult,
    PaymentStatus,
    SearchFlights,
)
from app.services.booking import BookingService
from app.services.payment import PaymentService


flight_mcp_client = FlightMCPClient()

ACTIVE_LIFECYCLES = {"held", "awaiting_payment"}

PASSENGER_DETAIL_FIELDS = ("title", "gender", "born_on", "email", "phone_number")


class ToolResult(NamedTuple):
    content: Any                     # sent back to the LLM as the tool message
    update: dict = {}                # AgentState changes, applied by tools.py
    events: list = []                # [(event_name, data)] for the browser
    summary: str | None = None       # one line for the step in the UI trace


def parse_arguments[T: BaseModel](tool_call: dict, model: type[T]) -> T:
    tool_name = tool_call["function"]["name"]

    try:
        return model.model_validate_json(tool_call["function"]["arguments"] or "{}")
    except ValidationError as exc:
        raise InvalidToolArguments(
            f"Invalid arguments for {tool_name}: {exc}"
        ) from exc


async def handle_search_flights(tool_call: dict, state: dict) -> ToolResult:
    request = parse_arguments(tool_call, SearchFlights)

    raw = await flight_mcp_client.search_flights(
        origin=request.origin,
        destination=request.destination,
        date=request.date.isoformat(),
        passengers=request.passengers,
        cabin=request.cabin.value,
    )

    try:
        flights = [Flight.model_validate(flight) for flight in json.loads(raw)]
    except (json.JSONDecodeError, ValidationError) as exc:
        raise InvalidUpstreamResponse(f"Flight search failed: {raw}") from exc

    results = {
        "search_id": f"srch_{uuid.uuid4().hex[:10]}",
        "query": {
            "origin": request.origin,
            "destination": request.destination,
            "date": request.date.isoformat(),
            "passengers": request.passengers,
            "cabin": request.cabin.value,
        },
        "flights": [flight_view(flight) for flight in flights],
    }

    return ToolResult(
        content=[flight.model_dump(mode="json") for flight in flights],
        events=[("flights.results", results)],
        summary=f"{len(flights)} flights found",
    )


async def handle_get_saved_passengers(tool_call: dict, state: dict) -> ToolResult:
    async with SessionLocal() as session:
        passengers = await BookingService(session).list_passengers(
            current_user_id(state)
        )

    content = [
        {
            **passenger_view(passenger),
            # the LLM must not book someone Duffel would reject
            "missing_details": [f for f in PASSENGER_DETAIL_FIELDS if getattr(passenger, f) is None],
        }
        for passenger in passengers
    ]

    return ToolResult(content, summary=f"{len(passengers)} saved passenger(s)")


async def handle_book_flight(tool_call: dict, state: dict) -> ToolResult:
    """Runs only AFTER the approval node said yes (see graph.route_after_llm)."""
    request = parse_arguments(tool_call, BookFlight)
    user_id = current_user_id(state)

    async with SessionLocal() as session:
        service = BookingService(session)

        # Change flow: release the current hold before taking a new one.
        current = state.get("booking") or {}
        if current.get("lifecycle") in ACTIVE_LIFECYCLES and state.get("db_booking_id"):
            await service.cancel_booking(user_id, uuid.UUID(state["db_booking_id"]))

        db_booking = await service.book_flight(user_id, request)

        passengers = await service.passenger_repository.get_passengers_by_ids(
            [uuid.UUID(pid) for pid in request.passenger_ids]
        )

    booking = to_booking_state(db_booking)

    return ToolResult(
        content=booking,
        update={
            "booking": booking,
            "db_booking_id": str(db_booking.id),
            "payment": None,
        },
        events=[
            ("booking.updated", booking_view(db_booking, passengers)),
            ("payment.updated", None),
        ],
        summary=f"Held · ref {db_booking.booking_reference}",
    )


async def handle_create_payment(tool_call: dict, state: dict) -> ToolResult:
    async with SessionLocal() as session:
        payment, db_booking = await PaymentService(session).create_payment(
            current_user_id(state),
            current_booking_id(state),
        )
        passengers = await BookingService(session).booking_passengers(db_booking)

    return payment_result(payment, db_booking, passengers, "Checkout created")


async def handle_complete_payment(tool_call: dict, state: dict) -> ToolResult:
    async with SessionLocal() as session:
        payment, db_booking = await PaymentService(session).complete_payment(
            current_user_id(state),
            current_booking_id(state),
        )
        passengers = await BookingService(session).booking_passengers(db_booking)

    return payment_result(payment, db_booking, passengers, f"Payment {payment.status.value}")


# --- translation helpers ---------------------------------------------------

def current_user_id(state: dict) -> uuid.UUID:
    return uuid.UUID(state["user_id"])


def current_booking_id(state: dict) -> uuid.UUID:
    if not state.get("db_booking_id"):
        raise AppError("There is no booking yet. Book a flight first.")

    return uuid.UUID(state["db_booking_id"])


def to_booking_state(db_booking: db.Booking) -> dict:
    # booking_id is the provider's ID; our database UUID stays in db_booking_id
    return Booking(
        booking_id=db_booking.provider_booking_id,
        booking_reference=db_booking.booking_reference,
        lifecycle=BookingLifecycle[db_booking.status.name],
        total_amount=float(db_booking.total_amount),
        currency=db_booking.currency,
        payment_required_by=db_booking.payment_required_by,
    ).model_dump(mode="json")


def to_payment_state(payment: db.Payment) -> dict:
    return PaymentResult(
        payment_id=payment.provider_payment_id,
        status=PaymentStatus(payment.status.value),
        amount=float(payment.amount),
        currency=payment.currency,
    ).model_dump(mode="json")


def payment_result(payment: db.Payment, db_booking: db.Booking, passengers: list, summary: str) -> ToolResult:
    payment_state = to_payment_state(payment)
    booking_state = to_booking_state(db_booking)

    return ToolResult(
        content={"payment": payment_state, "booking": booking_state},
        update={"payment": payment_state, "booking": booking_state},
        events=[
            ("payment.updated", payment_view(payment)),
            ("booking.updated", booking_view(db_booking, passengers)),
        ],
        summary=summary,
    )
