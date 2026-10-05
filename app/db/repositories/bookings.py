import uuid
from decimal import Decimal
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db.models import (
    Booking,
    BookingPassenger,
    BookingStatus,
    Flight,
)


class BookingRepository:

    def __init__(self, session: AsyncSession):
        self.session = session

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
        passenger_ids: list[uuid.UUID],
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

            # Flight snapshot
            flight_number=flight.flight_number,
            flight_name=flight.flight_name,

            origin_airport_code=flight.origin_airport_code,
            origin_airport_name=flight.origin_airport_name,

            destination_airport_code=flight.destination_airport_code,
            destination_airport_name=flight.destination_airport_name,

            departure_at=flight.departure_datetime,
            arrival_at=flight.arrival_datetime,

            cabin=flight.cabin,
        )

        self.session.add(booking)

        await self.session.flush()

        for passenger_id in passenger_ids:
            booking_passenger = BookingPassenger(
                booking_id=booking.id,
                passenger_id=passenger_id,
            )

            self.session.add(booking_passenger)

        return booking

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