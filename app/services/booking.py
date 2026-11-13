import uuid
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError, FlightNotFound, PassengerInUse, PassengerNotFound
from app.db import models as db
from app.db.repositories.bookings import BookingRepository
from app.db.repositories.flights import FlightRepository
from app.db.repositories.passengers import PassengerRepository
from app.models import BookFlight, Flight, Passenger
from app.providers import all_providers
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
        flight_provider: FlightProvider | None = None,
    ):
        self.session = session
        self.flight_provider = flight_provider or all_providers.flight_provider

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

    async def get_passenger(
        self,
        user_id: uuid.UUID,
        passenger_id: uuid.UUID,
    ) -> db.Passenger:
        """The user's saved passenger. Someone else's looks exactly like a missing one."""

        passenger = await self.passenger_repository.get_user_passenger(
            user_id,
            passenger_id,
        )

        if passenger is None:
            raise PassengerNotFound("Passenger not found.")

        return passenger

    async def create_passenger(
        self,
        user_id: uuid.UUID,
        passenger: dict,
    ) -> db.Passenger:

        [created] = await self.add_passengers(user_id, [passenger])

        return created

    async def update_passenger(
        self,
        user_id: uuid.UUID,
        passenger_id: uuid.UUID,
        changes: dict,
    ) -> db.Passenger:
        """Edit a saved passenger. Existing bookings keep the details they were booked with."""

        passenger = await self.get_passenger(user_id, passenger_id)

        if changes:
            await self.passenger_repository.update_passenger(passenger, changes)
            await self.session.commit()

        return passenger

    async def delete_passenger(
        self,
        user_id: uuid.UUID,
        passenger_id: uuid.UUID,
    ) -> None:
        """
        Delete a saved passenger. Existing bookings keep the details they were booked with.

        Refused while the passenger is on a booking that is awaiting payment with a
        deadline still ahead. Held, confirmed, cancelled bookings, a passed deadline
        or no deadline at all don't block. Ownership is checked first, so someone
        else's passenger is always "not found", never "in use".
        """

        passenger = await self.get_passenger(user_id, passenger_id)

        open_booking = await self.booking_repository.find_open_payment_booking_for_passenger(passenger.id)

        if open_booking is not None:
            raise PassengerInUse(open_booking.booking_reference, open_booking.payment_required_by)

        await self.passenger_repository.delete_passenger(passenger)

        await self.session.commit()

    async def book_flight(
        self,
        user_id: uuid.UUID,
        request: BookFlight,
    ) -> db.Booking:

        passengers = await self._get_user_passengers(
            user_id,
            request.passenger_ids,
        )

        flight = await self.flight_provider.fetch_flight_details(
            request.flight_id
        )

        if flight is None:
            raise FlightNotFound(f"Flight {request.flight_id} not found.")

        result = await self.flight_provider.book_flight(
            request,
            flight,
            passengers=passengers,
        )

        db_flight = await self._get_or_create_flight(flight)

        booking = await self.booking_repository.create_booking(
            user_id=user_id,
            flight=db_flight,
            booking_reference=result.booking_reference,
            provider_booking_id=result.booking_id,
            total_amount=Decimal(str(result.total_amount)),
            currency=result.currency,
            passengers=passengers,
            status=db.BookingStatus.HELD,
            payment_required_by=result.payment_required_by,
        )

        await self.session.commit()

        return booking

    async def cancel_booking(
        self,
        user_id: uuid.UUID,
        booking_id: uuid.UUID,
    ) -> db.Booking:
        """Release the hold at the provider, then mark it cancelled. Idempotent."""

        booking = await self.booking_repository.get_booking(booking_id)

        if booking is None or booking.user_id != user_id:
            raise AppError("Booking not found.")

        if booking.status == db.BookingStatus.CANCELLED:
            return booking

        if booking.status not in (db.BookingStatus.HELD, db.BookingStatus.AWAITING_PAYMENT):
            raise AppError("Only a held booking can be cancelled. Paid bookings need a refund.")

        await self.flight_provider.cancel_order(booking.provider_booking_id)

        await self.booking_repository.update_status(
            booking.id,
            db.BookingStatus.CANCELLED,
        )

        await self.session.commit()

        return booking

    async def add_passengers(
        self,
        user_id: uuid.UUID,
        passengers: list[dict],
    ) -> list[db.Passenger]:
        """Save new passengers (title, given_name, family_name, gender, born_on, email, phone_number)."""

        created = [
            await self.passenger_repository.create_passenger(user_id=user_id, **passenger)
            for passenger in passengers
        ]

        await self.session.commit()

        return created

    async def booking_passengers(
        self,
        booking: db.Booking,
    ) -> list[db.BookingPassenger]:
        """The travellers as booked, not the (possibly edited or deleted) saved passengers."""

        return await self.booking_repository.get_booking_passengers(booking.id)

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
