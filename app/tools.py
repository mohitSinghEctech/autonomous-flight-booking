import json

from pydantic import ValidationError
from app.core.errors import InvalidToolArguments

from app.providers.all_providers import flight_provider
from .models import SearchFlights, Flight, BookFlight

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
    
async def execute_book_flight(arguments):
    try:
        request = BookFlight.model_validate(arguments)
    except ValidationError as exc:
        raise InvalidToolArguments(f"Invalid arguments for book_flight: {exc}") from exc
    result = await book_flight(request)
    
    return json.dumps(result)

async def search_flights(request_model: SearchFlights) -> list[Flight]:
    return await flight_provider.search_flights(request_model)

async def book_flight(request_model: BookFlight):
    return await flight_provider.book_flight(request_model)

async def fetch_flight_details(flight_id: str) -> Flight | None:
    return await flight_provider.fetch_flight_details(flight_id)

TOOL_HANDLERS = {
    "search_flights": execute_search_flights,
    "book_flight": execute_book_flight
}