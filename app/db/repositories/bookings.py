import uuid
from decimal import Decimal
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db.models import (
    Booking,
    BookingPassenger,
    BookingStatus,
    Flight,
)
from app.models import Passenger


class BookingRepository:

    def __init__(self, session: AsyncSession):
        self.session = session
        
    async def list_user_bookings(
        self,
        user_id: uuid.UUID,
        limit: int
    ):
        """The user's bookings, newest first, at most `limit`."""
        result = await self.session.execute(
            select(Booking)
            .where(Booking.user_id == user_id)
            .order_by(Booking.created_at.desc(), Booking.id.desc())
            .limit(limit)
        )
        
        return list(result.scalars().all())

    async def get_booking(
        self,
        booking_id: uuid.UUID,
    ) -> Booking | None:

        result = await self.session.execute(
            select(Booking)
            .options(
                selectinload(Booking.booking_passengers),
                selectinload(Booking.payments),
            )
            .where(Booking.id == booking_id)
        )

        return result.scalar_one_or_none()

    async def get_by_reference(
        self,
        booking_reference: str,
    ) -> Booking | None:

        result = await self.session.execute(
            select(Booking)
            .where(
                Booking.booking_reference == booking_reference
            )
        )

        return result.scalar_one_or_none()

    async def get_user_bookings(
        self,
        user_id: uuid.UUID,
    ) -> list[Booking]:

        result = await self.session.execute(
            select(Booking)
            .where(Booking.user_id == user_id)
            .order_by(Booking.created_at.desc())
        )

        return list(result.scalars().all())

    async def create_booking(
        self,
        user_id: uuid.UUID,
        flight: Flight,
        booking_reference: str,
        provider_booking_id: str,
        total_amount: Decimal,
        currency: str,
        passengers: list[Passenger],
        status: BookingStatus,
        payment_required_by: datetime | None = None,
    ) -> Booking:

        booking = Booking(
            user_id=user_id,
            flight_id=flight.id,
            booking_reference=booking_reference,
            provider_booking_id=provider_booking_id,
            status=status,
            total_amount=total_amount,
            currency=currency,
            payment_required_by=payment_required_by,

            flight_number=flight.flight_number,
            flight_name=flight.flight_name,

            origin_airport_code=flight.origin_airport_code,
            origin_airport_name=flight.origin_airport_name,

            destination_airport_code=flight.destination_airport_code,
            destination_airport_name=flight.destination_airport_name,

            departure_at=flight.departure_datetime,
            arrival_at=flight.arrival_datetime,

            cabin=flight.cabin,

            # The travellers exactly as sent to the airline. Later edits or
            # deletes of the saved passengers don't touch these rows.
            booking_passengers=[
                BookingPassenger(
                    passenger_id=uuid.UUID(passenger.id),
                    title=passenger.title,
                    given_name=passenger.given_name,
                    family_name=passenger.family_name,
                    gender=passenger.gender,
                    born_on=passenger.born_on,
                    email=passenger.email,
                    phone_number=passenger.phone_number,
                )
                for passenger in passengers
            ],
        )

        self.session.add(booking)

        await self.session.flush()

        return booking

    async def get_booking_passengers(
        self,
        booking_id: uuid.UUID,
    ) -> list[BookingPassenger]:
        """The travellers on a booking, as they were booked."""

        result = await self.session.execute(
            select(BookingPassenger)
            .where(BookingPassenger.booking_id == booking_id)
            .order_by(BookingPassenger.given_name, BookingPassenger.family_name, BookingPassenger.id)
        )

        return list(result.scalars().all())

    async def find_open_payment_booking_for_passenger(
        self,
        passenger_id: uuid.UUID,
    ) -> Booking | None:
        """
        A booking with this saved passenger that is awaiting payment and whose
        payment deadline is still ahead (database clock). No deadline -> not open.
        With several, the one with the latest deadline: that's when the last one ends.
        """
        result = await self.session.execute(
            select(Booking)
            .join(BookingPassenger, BookingPassenger.booking_id == Booking.id)
            .where(
                BookingPassenger.passenger_id == passenger_id,
                Booking.status == BookingStatus.AWAITING_PAYMENT,
                Booking.payment_required_by.is_not(None),
                Booking.payment_required_by > func.now(),
            )
            .order_by(Booking.payment_required_by.desc())
            .limit(1)
        )

        return result.scalar_one_or_none()

    async def update_status(
        self,
        booking_id: uuid.UUID,
        status: BookingStatus,
    ) -> Booking | None:

        booking = await self.get_booking(booking_id)

        if booking is None:
            return None

        booking.status = status

        await self.session.flush()

        return booking