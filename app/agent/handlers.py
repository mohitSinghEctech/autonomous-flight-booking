"""
Handlers translate an LLM tool call into one application operation.

Each one: parse arguments -> call a service/provider -> return a ToolResult.
Business rules live in the services, not here.
"""
import json
import uuid
from typing import Any, NamedTuple

from pydantic import BaseModel, ValidationError

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


class ToolResult(NamedTuple):
    content: Any                 # sent back to the LLM as the tool message
    update: dict = {}            # AgentState changes, applied by tools.py


def parse_arguments[T: BaseModel](tool_call: dict, model: type[T]) -> T:
    tool_name = tool_call["function"]["name"]

    try:
        return model.model_validate_json(tool_call["function"]["arguments"])
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

    return ToolResult([flight.model_dump(mode="json") for flight in flights])


async def handle_get_saved_passengers(tool_call: dict, state: dict) -> ToolResult:
    async with SessionLocal() as session:
        passengers = await BookingService(session).list_passengers(
            current_user_id(state)
        )

    return ToolResult([
        {
            "id": str(passenger.id),
            "name": f"{passenger.given_name} {passenger.family_name}",
        }
        for passenger in passengers
    ])


async def handle_book_flight(tool_call: dict, state: dict) -> ToolResult:
    request = parse_arguments(tool_call, BookFlight)

    async with SessionLocal() as session:
        db_booking = await BookingService(session).book_flight(
            current_user_id(state),
            request,
        )

    booking = to_booking_state(db_booking)

    return ToolResult(
        content=booking,
        update={
            "booking": booking,
            "db_booking_id": str(db_booking.id),
        },
    )


async def handle_create_payment(tool_call: dict, state: dict) -> ToolResult:
    async with SessionLocal() as session:
        payment, db_booking = await PaymentService(session).create_payment(
            current_user_id(state),
            current_booking_id(state),
        )

    return payment_result(payment, db_booking)


async def handle_complete_payment(tool_call: dict, state: dict) -> ToolResult:
    async with SessionLocal() as session:
        payment, db_booking = await PaymentService(session).complete_payment(
            current_user_id(state),
            current_booking_id(state),
        )

    return payment_result(payment, db_booking)


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


def payment_result(payment: db.Payment, db_booking: db.Booking) -> ToolResult:
    payment_state = to_payment_state(payment)
    booking_state = to_booking_state(db_booking)

    return ToolResult(
        content={"payment": payment_state, "booking": booking_state},
        update={"payment": payment_state, "booking": booking_state},
    )
