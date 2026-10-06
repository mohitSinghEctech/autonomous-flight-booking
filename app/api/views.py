"""
Translate our models (DB rows, domain objects) into the contract shapes the UI reads.

The only place that knows both sides. Rules from the contract:
  - booking.booking_id is the PROVIDER id, never our DB uuid
  - flight times stay local (no offset); other timestamps are UTC
  - the checkout block is present only while the payment is open
"""
from datetime import datetime

from app.db import models as db
from app.models import BookingLifecycle, Flight
from app.providers import all_providers


def iso(value) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)


def local_time(value) -> str | None:
    """Flight times are local airport time: drop any offset, never convert."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.replace(tzinfo=None).isoformat()
    return str(value)[:19]


def passenger_view(passenger: db.Passenger) -> dict:
    return {"id": str(passenger.id), "name": f"{passenger.given_name} {passenger.family_name}"}


def flight_view(flight: Flight | dict) -> dict:
    f = flight if isinstance(flight, Flight) else Flight.model_validate(flight)
    return {
        "flight_id": f.flight_id,
        "flight_name": f.flight_name,
        "origin": {"airport_code": f.origin.airport_code, "airport_name": f.origin.airport_name},
        "destination": {"airport_code": f.destination.airport_code, "airport_name": f.destination.airport_name},
        "departure_datetime": local_time(f.departure_datetime),
        "arrival_datetime": local_time(f.arrival_datetime),
        "price": f.price,
        "currency": f.currency,
        "cabin": f.cabin.value,
        "duration_minutes": f.duration_minutes,
        "expires_at": iso(f.expires_at),
        "stops": [
            {
                "airport": {"airport_code": s.airport.airport_code, "airport_name": s.airport.airport_name},
                "arrival_datetime": local_time(s.arrival_datetime),
                "departure_datetime": local_time(s.departure_datetime),
            }
            for s in f.stops
        ],
    }


def flight_from_booking(booking: db.Booking) -> dict:
    """The booking row keeps a snapshot of the flight; rebuild a FlightView from it."""
    return {
        "flight_id": booking.flight_number,
        "flight_name": booking.flight_name,
        "origin": {"airport_code": booking.origin_airport_code, "airport_name": booking.origin_airport_name},
        "destination": {"airport_code": booking.destination_airport_code, "airport_name": booking.destination_airport_name},
        "departure_datetime": local_time(booking.departure_at),
        "arrival_datetime": local_time(booking.arrival_at),
        "price": float(booking.total_amount),
        "currency": booking.currency,
        "cabin": booking.cabin,
        "duration_minutes": None,
        "expires_at": None,
        "stops": [],
    }


def booking_view(booking: db.Booking, passengers: list[db.Passenger]) -> dict:
    return {
        "booking_id": booking.provider_booking_id,
        "booking_reference": booking.booking_reference,
        "lifecycle": BookingLifecycle[booking.status.name].value,
        "total_amount": float(booking.total_amount),
        "currency": booking.currency,
        "payment_required_by": iso(booking.payment_required_by),
        "flight_id": booking.flight_number,          # = provider offer id, matches the flight list
        "passengers": [passenger_view(p) for p in passengers],
    }


def payment_view(payment: db.Payment) -> dict:
    status = payment.status.value
    is_open = status in ("created", "pending")
    provider = all_providers.payment_provider

    return {
        "payment_id": payment.provider_payment_id,
        "status": status,
        "amount": float(payment.amount),
        "currency": payment.currency,
        "checkout": {
            "provider": "cashfree",
            "mode": provider.mode,
            "payment_session_id": payment.payment_session_id,
        } if is_open and payment.payment_session_id else None,
        "failure_reason": "The payment did not go through. Nothing was charged." if status == "failed" else None,
        "paid_at": iso(payment.updated_at) if status == "paid" else None,
    }
