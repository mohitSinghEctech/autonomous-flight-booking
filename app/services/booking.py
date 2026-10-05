import uuid
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError, FlightNotFound, PassengerNotFound
from app.db import models as db
from app.db.repositories.bookings import BookingRepository
from app.db.repositories.flights import FlightRepository
from app.db.repositories.passengers import PassengerRepository
from app.models import BookFlight, Flight, Passenger
from app.providers.all_providers import flight_provider as default_flight_provider
from app.providers.flights.base import FlightProvider


FLIGHT_PROVIDER_NAME = "duffel"


class BookingService:
    """
    Owns the booking workflow:
    validate passengers -> fetch flight -> hold with provider -> persist.
    """

    def __init__(
        self,
        session: AsyncSession,
        flight_provider: FlightProvider = default_flight_provider,
    ):
        self.session = session
        self.flight_provider = flight_provider

        self.booking_repository = BookingRepository(session)
        self.flight_repository = FlightRepository(session)
        self.passenger_repository = PassengerRepository(session)

    async def list_passengers(
        self,
        user_id: uuid.UUID,
    ) -> list[db.Passenger]:

        return await self.passenger_repository.get_passengers_by_user(
            user_id
        )

    async def book_flight(
        self,
        user_id: uuid.UUID,
        request: BookFlight,
    ) -> db.Booking:

        # 1. Passengers must exist, belong to this user, and be complete
        passengers = await self._get_user_passengers(
            user_id,
            request.passenger_ids,
        )

        # 2. Re-fetch the offer so we book the current price, not a stale one
        flight = await self.flight_provider.fetch_flight_details(
            request.flight_id
        )

        if flight is None:
            raise FlightNotFound(f"Flight {request.flight_id} not found.")

        # 3. Place the hold with the provider
        result = await self.flight_provider.book_flight(
            request,
            flight,
            passengers=passengers,
        )

        # 4. Persist flight + booking in one transaction
        db_flight = await self._get_or_create_flight(flight)

        booking = await self.booking_repository.create_booking(
            user_id=user_id,
            flight=db_flight,
            booking_reference=result.booking_reference,
            provider_booking_id=result.booking_id,
            total_amount=Decimal(str(result.total_amount)),
            currency=result.currency,
            passenger_ids=[uuid.UUID(p.id) for p in passengers],
            status=db.BookingStatus.HELD,
            payment_required_by=result.payment_required_by,
        )

        await self.session.commit()

        return booking

    async def get_booking(
        self,
        booking_id: uuid.UUID,
    ):

        return await self.booking_repository.get_booking(
            booking_id
        )

    async def get_user_bookings(
        self,
        user_id: uuid.UUID,
    ):

        return await self.booking_repository.get_user_bookings(
            user_id
        )

    async def _get_user_passengers(
        self,
        user_id: uuid.UUID,
        passenger_ids: list[str],
    ) -> list[Passenger]:

        try:
            ids = [uuid.UUID(passenger_id) for passenger_id in passenger_ids]
        except ValueError as exc:
            raise PassengerNotFound(
                f"Invalid passenger ID in {passenger_ids}."
            ) from exc

        passengers = await self.passenger_repository.get_passengers_by_ids(ids)

        if len(passengers) != len(set(ids)):
            raise PassengerNotFound("One or more passengers were not found.")

        for passenger in passengers:
            if passenger.user_id != user_id:
                raise PassengerNotFound(
                    f"Passenger {passenger.id} does not belong to user."
                )

        return [to_domain_passenger(passenger) for passenger in passengers]

    async def _get_or_create_flight(self, flight: Flight) -> db.Flight:

        db_flight = await self.flight_repository.get_by_provider_reference(
            provider=FLIGHT_PROVIDER_NAME,
            provider_reference=flight.provider_reference or flight.flight_id,
        )

        if db_flight is None:
            db_flight = await self.flight_repository.create_flight(
                flight=flight,
                provider=FLIGHT_PROVIDER_NAME,
            )

        return db_flight


def to_domain_passenger(passenger: db.Passenger) -> Passenger:
    """The flight provider needs full travel details, not just a name."""

    missing = [
        field
        for field in ("title", "gender", "born_on", "email", "phone_number")
        if getattr(passenger, field) is None
    ]

    if missing:
        raise AppError(
            f"Passenger {passenger.given_name} {passenger.family_name} "
            f"is missing travel details: {', '.join(missing)}."
        )

    return Passenger(
        id=str(passenger.id),
        title=passenger.title,
        given_name=passenger.given_name,
        family_name=passenger.family_name,
        gender=passenger.gender,
        born_on=passenger.born_on,
        email=passenger.email,
        phone_number=passenger.phone_number,
    )
