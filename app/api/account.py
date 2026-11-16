"""
Account endpoints: plain REST, the response body is the result (no SSE events).
"""
import uuid

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.auth import current_user_id
from app.api.errors import ApiError
from app.api.events import NewPassenger, PassengerUpdate
from app.api.views import booking_detail_view, booking_summary_view, saved_passenger_view
from app.core.errors import PassengerInUse, PassengerNotFound
from app.db.dependencies import get_db
from app.db.repositories.bookings import BookingRepository
from app.services.booking import BookingService

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
        "next_cursor": None,
    }
    
@account.get("/bookings/{booking_id}")
async def get_booking(
    booking_id: str,
    user_id: str = Depends(current_user_id),
    db: AsyncSession = Depends(get_db),
):
    booking = await find_user_booking(db, booking_id, user_id)

    passengers = await BookingService(db).booking_passengers(booking)

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


# Saved passengers. Only the caller's own: any other id is a 404, exactly like
# a missing one. Editing or deleting one never changes existing bookings (they
# keep the travellers' details as booked). Delete is refused (409
# passenger_in_use) only while the passenger is on a booking awaiting payment
# whose deadline is still ahead.

PASSENGER_NOT_FOUND = ("passenger_not_found", "Passenger not found.")


@account.get("/passengers")
async def list_saved_passengers(
    user_id: str = Depends(current_user_id),
    db: AsyncSession = Depends(get_db),
):
    passengers = await BookingService(db).list_passengers(uuid.UUID(user_id))

    return {"items": [saved_passenger_view(p) for p in passengers]}


@account.post("/passengers", status_code=201)
async def create_saved_passenger(
    body: NewPassenger,
    user_id: str = Depends(current_user_id),
    db: AsyncSession = Depends(get_db),
):
    passenger = await BookingService(db).create_passenger(uuid.UUID(user_id), body.model_dump())

    return saved_passenger_view(passenger)


@account.get("/passengers/{passenger_id}")
async def get_saved_passenger(
    passenger_id: str,
    user_id: str = Depends(current_user_id),
    db: AsyncSession = Depends(get_db),
):
    passenger = await owned(BookingService(db).get_passenger, user_id, passenger_id)

    return saved_passenger_view(passenger)


@account.patch("/passengers/{passenger_id}")
async def update_saved_passenger(
    passenger_id: str,
    body: PassengerUpdate,
    user_id: str = Depends(current_user_id),
    db: AsyncSession = Depends(get_db),
):
    passenger = await owned(BookingService(db).update_passenger, user_id, passenger_id, body.changes())

    return saved_passenger_view(passenger)


@account.delete("/passengers/{passenger_id}", status_code=204)
async def delete_saved_passenger(
    passenger_id: str,
    user_id: str = Depends(current_user_id),
    db: AsyncSession = Depends(get_db),
):
    try:
        await owned(BookingService(db).delete_passenger, user_id, passenger_id)
    except PassengerInUse as exc:
        raise ApiError(409, "passenger_in_use", str(exc))

    return Response(status_code=204)


async def owned(action, user_id: str, passenger_id: str, *args):
    """Run a service call on the caller's passenger; a bad id or someone else's is a 404."""
    try:
        passenger_uuid = uuid.UUID(passenger_id)
    except ValueError:
        raise ApiError(404, *PASSENGER_NOT_FOUND)

    try:
        return await action(uuid.UUID(user_id), passenger_uuid, *args)
    except PassengerNotFound:
        raise ApiError(404, *PASSENGER_NOT_FOUND)
