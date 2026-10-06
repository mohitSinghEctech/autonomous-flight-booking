from abc import ABC, abstractmethod

from app.core.errors import AppError
from app.models import BookFlight, BookingResult, Flight, Passenger, SearchFlights


class FlightProvider(ABC):
    @abstractmethod
    async def search_flights(self, request: SearchFlights) -> list[Flight]:
        pass

    @abstractmethod
    async def book_flight(self, request: BookFlight, flight: Flight, passengers: list[Passenger]) -> BookingResult:
        pass

    @abstractmethod
    async def fetch_flight_details(self, flight_id: str) -> Flight | None:
        pass

    async def cancel_order(self, provider_booking_id: str) -> None:
        """Release a held order at the provider. Not every provider supports it."""
        raise AppError("This flight provider cannot cancel orders.")
