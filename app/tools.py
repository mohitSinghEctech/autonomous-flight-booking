from datetime import date, timedelta
import json


from .mock.flight_vendor import (
    book_flight as vendor_book_flight,
    search_flights as vendor_search_flights,
    get_flight as vendor_get_flight,
)
from .models import SearchFlights, Flight, Cabin, BookFlight

def execute_search_flights(arguments):
    request = SearchFlights.model_validate(arguments)
    result = search_flights(request)
    
    return json.dumps([
        flight.model_dump(mode="json")
        for flight in result
    ])
    
def execute_book_flight(arguments):
    request = BookFlight.model_validate(arguments)
    result = book_flight(request)
    
    return json.dumps(result)

def search_flights(request_model: SearchFlights) -> list[Flight]:
    return vendor_search_flights(request_model)

def book_flight(request_model: BookFlight):
    return vendor_book_flight(request_model)

def get_flight(flight_id: str) -> Flight | None:
    return vendor_get_flight(flight_id)

TOOL_HANDLERS = {
    "search_flights": execute_search_flights,
    "book_flight": execute_book_flight
}