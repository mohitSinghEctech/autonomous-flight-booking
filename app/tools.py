import json

from app.providers.user.passengers_mock import (
    get_saved_passengers as load_saved_passengers,
    get_passengers_by_ids
    )
from app.core.errors import InvalidToolArguments
from app.providers.all_providers import flight_provider
from .models import SearchFlights, Flight, BookFlight, BookingLifecycle, Booking, booking_lifecycle_from_status

from pydantic import ValidationError


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

async def search_flights(request_model: SearchFlights) -> list[Flight]:
    return await flight_provider.search_flights(request_model)

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
    "get_saved_passengers": execute_get_saved_passengers
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