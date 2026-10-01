from abc import ABC, abstractmethod
from app.models import Flight, Passenger, SearchFlights, BookFlight

class FlightProvider(ABC):
    @abstractmethod
    async def search_flights(self, request: SearchFlights) -> list[Flight]:
        pass
    
    @abstractmethod
    async def book_flight(self, request: BookFlight, flight: Flight, passengers: list[Passenger]) -> dict:
        pass
    
    @abstractmethod
    async def fetch_flight_details(self, flight_id: str) -> Flight | None:
        pass
    