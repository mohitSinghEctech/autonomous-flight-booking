from abc import ABC, abstractmethod
from decimal import Decimal

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
    
    async def pay_order(self, provider_booking_id: str, amount: Decimal, currency: str) -> None:
        """Pay the provider for a held order, so the airline issues the ticket.
        Not every provider supports it (same pattern as cancel_order)."""
        raise AppError("This flight provider cannot pay for orders.")

    async def cancel_order(self, provider_booking_id: str) -> None:
        """Release a held order at the provider. Not every provider supports it."""
        raise AppError("This flight provider cannot cancel orders.")
