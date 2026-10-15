"""
Account endpoints: plain REST, the response body is the result (no SSE events).
"""
import uuid

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.auth import current_user_id
from app.api.errors import ApiError
from app.api.views import booking_detail_view, booking_summary_view
from app.db.dependencies import get_db
from app.db.repositories.bookings import BookingRepository
from app.db.repositories.passengers import PassengerRepository

account = APIRouter(prefix="/api")


@account.get("/bookings")
async def list_bookings(
    limit: int = Query(default=20, ge=1, le=50),
    user_id: str = Depends(current_user_id),
    db: AsyncSession = Depends(get_db),
):
    bookings = await BookingRepository(db).list_user_bookings(uuid.UUID(user_id), limit)

    return {
        "items": [booking_summary_view(booking) for booking in bookings],
        "next_cursor": None,          # pagination comes in the next step
    }
    
@account.get("/bookings/{booking_id}")
async def get_booking(
    booking_id: str,
    user_id: str = Depends(current_user_id),
    db: AsyncSession = Depends(get_db),
):
    booking = await find_user_booking(db, booking_id, user_id)

    passenger_ids = [link.passenger_id for link in booking.booking_passengers]
    passengers = await PassengerRepository(db).get_passengers_by_ids(passenger_ids)

    return booking_detail_view(booking, passengers)


async def find_user_booking(db: AsyncSession, booking_id: str, user_id: str):
    """The caller's booking, or 404. A bad id and someone else's id look the same."""
    not_found = ApiError(404, "booking_not_found", "Booking not found.")

    try:
        booking_uuid = uuid.UUID(booking_id)
    except ValueError:
        raise not_found

    booking = await BookingRepository(db).get_booking(booking_uuid)

    if booking is None or booking.user_id != uuid.UUID(user_id):
        raise not_found

    return booking