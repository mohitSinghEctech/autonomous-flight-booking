import json

from app.providers.user.passengers_mock import (
    get_saved_passengers as load_saved_passengers,
    get_passengers_by_ids
    )
from app.core.errors import InvalidToolArguments
from app.providers.all_providers import flight_provider, payment_provider
from .models import SearchFlights, Flight, BookFlight, BookingLifecycle, Booking, booking_lifecycle_from_status
from app.mcp.client import FlightMCPClient

from pydantic import ValidationError

flight_mcp_client = FlightMCPClient()


async def execute_search_flights(arguments):
    try:
        request = SearchFlights.model_validate(arguments)
    except ValidationError as exc:
        raise InvalidToolArguments(f"Invalid arguments for search_flights: {exc}") from exc
    result = await search_flights(request)
    
    return json.dumps([
        flight.model_dump(mode="json")
        for flight in result
    ])
    
async def execute_book_flight(arguments, flight: Flight):
    try:
        request = BookFlight.model_validate(arguments)
    except ValidationError as exc:
        raise InvalidToolArguments(f"Invalid arguments for book_flight: {exc}") from exc
    
    result = await book_flight(request, flight)
    
    return json.dumps(result.model_dump(mode="json"))

async def execute_get_saved_passengers(arguments=None):
    passengers = load_saved_passengers()

    return json.dumps([
        {
            "id": passenger.id,
            "name": f"{passenger.given_name} {passenger.family_name}",
        }
        for passenger in passengers
    ])
    
async def execute_create_payment(booking: Booking):
    if booking is None:
        raise InvalidToolArguments("No booking available to create payment for.")
    
    if booking.lifecycle != BookingLifecycle.HELD:
        raise InvalidToolArguments(
            "Payment can only be created for a held booking."
        )
        
    result = await payment_provider.create_payment(
        booking_id=booking.booking_id,
        amount=booking.total_amount,
        currency=booking.currency
    )
    
    return json.dumps(result.model_dump(mode="json"))

async def execute_complete_payment(payment: dict):
    if payment is None:
        raise InvalidToolArguments("There is no payment available to complete.")

    payment_id = payment.get("payment_id")

    if not payment_id:
        raise InvalidToolArguments("Payment ID is missing.")

    result = await payment_provider.complete_payment(payment_id, payment.get("amount"), currency=payment.get("currency"))

    return json.dumps(result.model_dump(mode="json"))

async def search_flights(request_model: SearchFlights) -> list[Flight]:
    result = await flight_mcp_client.search_flights(
        origin=request_model.origin,
        destination=request_model.destination,
        date=request_model.date.isoformat(),
        passengers=request_model.passengers,
        cabin=request_model.cabin.value,
    )

    decoded = json.loads(result)

    return [
        Flight.model_validate(flight)
        for flight in decoded
    ]

async def book_flight(request_model: BookFlight, flight: Flight):
    passengers = get_passengers_by_ids(request_model.passenger_ids)
    result = await flight_provider.book_flight(
        request_model, 
        flight,
        passengers=passengers
    )
    lifecycle = booking_lifecycle_from_status(result.status)
    
    return Booking(
        booking_id=result.booking_id,
        booking_reference=result.booking_reference,
        lifecycle=lifecycle,
        total_amount=result.total_amount,
        currency=result.currency,
        payment_required_by=result.payment_required_by
    )

async def fetch_flight_details(flight_id: str) -> Flight | None:
    return await flight_provider.fetch_flight_details(flight_id)


TOOL_HANDLERS = {
    "search_flights": execute_search_flights,
    "book_flight": execute_book_flight,
    "get_saved_passengers": execute_get_saved_passengers,
    "create_payment": execute_create_payment,
    "complete_payment": execute_complete_payment,
}

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
        "Place a selected flight on hold. "
        "This does not complete payment or confirm the booking. "
        "flight_id must be the exact flight_id returned by search_flights. "
        "passenger_ids must be IDs returned by get_saved_passengers."
    ),
    "parameters": BookFlight.model_json_schema(),
}

get_saved_passengers_tool = {
    "name": "get_saved_passengers",
    "description": (
        "Get the passengers saved in the customer's profile. "
        "Use their passenger IDs when booking a flight."
    ),
    "parameters": {
        "type": "object",
        "properties": {},
        "additionalProperties": False,
    },
}

create_payment_tool = {
    "name": "create_payment",
    "description": (
        "Create a payment for the current held booking. "
        "Use this only when the current booking lifecycle is HELD "
        "and the user wants to start the payment process. "
        "Do not use this for a booking that is already AWAITING_PAYMENT "
        "or when the user wants to complete an existing payment."
    ),
    "parameters": {
        "type": "object",
        "properties": {},
        "additionalProperties": False,
    },
}

complete_payment_tool = {
    "name": "complete_payment",
    "description": (
        "Complete the existing payment for the current booking. "
        "Use this when a payment has already been created and the user "
        "wants to complete or pay for it. "
        "Do not create a new payment."
    ),
    "parameters": {
        "type": "object",
        "properties": {},
        "additionalProperties": False,
    },
}