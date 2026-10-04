import uuid
from datetime import datetime, timezone
from decimal import Decimal
from enum import Enum

from sqlalchemy import (
    String,
    ForeignKey,
    DateTime,
    Enum as SQLEnum,
    Numeric,
    UniqueConstraint,
    Index,
)
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class BookingStatus(str, Enum):
    HELD = "hold"
    AWAITING_PAYMENT = "awaiting_payment"
    CONFIRMED = "confirmed"


class PaymentStatus(str, Enum):
    CREATED = "created"
    PENDING = "pending"
    PAID = "paid"
    FAILED = "failed"


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )

    given_name: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
    )

    family_name: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
    )

    passengers: Mapped[list["Passenger"]] = relationship(
        back_populates="user"
    )

    bookings: Mapped[list["Booking"]] = relationship(
        back_populates="user"
    )


class Passenger(Base):
    __tablename__ = "passengers"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )

    given_name: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
    )

    family_name: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id"),
        nullable=False,
    )

    user: Mapped["User"] = relationship(
        back_populates="passengers"
    )

    booking_passengers: Mapped[list["BookingPassenger"]] = relationship(
        back_populates="passenger"
    )


class Flight(Base):
    __tablename__ = "flights"

    __table_args__ = (
        UniqueConstraint(
            "provider",
            "provider_reference",
            name="uq_flight_provider_reference",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )

    provider: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
    )

    provider_reference: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
    )

    flight_number: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
    )

    flight_name: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
    )

    origin_airport_code: Mapped[str] = mapped_column(
        String(3),
        nullable=False,
    )

    origin_airport_name: Mapped[str] = mapped_column(
        String(150),
        nullable=False,
    )

    destination_airport_code: Mapped[str] = mapped_column(
        String(3),
        nullable=False,
    )

    destination_airport_name: Mapped[str] = mapped_column(
        String(150),
        nullable=False,
    )

    departure_datetime: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )

    arrival_datetime: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )

    cabin: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
    )

    stops: Mapped[list["FlightStop"]] = relationship(
        back_populates="flight"
    )

    bookings: Mapped[list["Booking"]] = relationship(
        back_populates="flight"
    )


class FlightStop(Base):
    __tablename__ = "flight_stops"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )

    flight_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("flights.id"),
        nullable=False,
    )

    stop_sequence: Mapped[int] = mapped_column(
        nullable=False,
    )

    airport_code: Mapped[str] = mapped_column(
        String(3),
        nullable=False,
    )

    airport_name: Mapped[str] = mapped_column(
        String(150),
        nullable=False,
    )

    departure_time: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )

    arrival_time: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )

    flight: Mapped["Flight"] = relationship(
        back_populates="stops"
    )


class Booking(Base):
    __tablename__ = "bookings"

    __table_args__ = (
        Index(
            "ix_bookings_user_id",
            "user_id",
        ),
        Index(
            "ix_bookings_flight_id",
            "flight_id",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id"),
        nullable=False,
    )

    flight_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("flights.id"),
        nullable=False,
    )

    booking_reference: Mapped[str] = mapped_column(
        String(50),
        unique=True,
        nullable=False,
    )

    booking_date: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )

    status: Mapped[BookingStatus] = mapped_column(
        SQLEnum(BookingStatus),
        nullable=False,
    )

    total_amount: Mapped[Decimal] = mapped_column(
        Numeric(12, 2),
        nullable=False,
    )

    currency: Mapped[str] = mapped_column(
        String(3),
        nullable=False,
    )

    payment_required_by: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    # Flight snapshot
    flight_number: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
    )

    flight_name: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
    )

    origin_airport_code: Mapped[str] = mapped_column(
        String(3),
        nullable=False,
    )

    origin_airport_name: Mapped[str] = mapped_column(
        String(150),
        nullable=False,
    )

    destination_airport_code: Mapped[str] = mapped_column(
        String(3),
        nullable=False,
    )

    destination_airport_name: Mapped[str] = mapped_column(
        String(150),
        nullable=False,
    )

    departure_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )

    arrival_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )

    cabin: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    user: Mapped["User"] = relationship(
        back_populates="bookings"
    )

    flight: Mapped["Flight"] = relationship(
        back_populates="bookings"
    )

    booking_passengers: Mapped[list["BookingPassenger"]] = relationship(
        back_populates="booking"
    )

    payments: Mapped[list["Payment"]] = relationship(
        back_populates="booking"
    )


class BookingPassenger(Base):
    __tablename__ = "booking_passengers"

    __table_args__ = (
        UniqueConstraint(
            "booking_id",
            "passenger_id",
            name="uq_booking_passenger",
        ),
        Index(
            "ix_booking_passengers_booking_id",
            "booking_id",
        ),
        Index(
            "ix_booking_passengers_passenger_id",
            "passenger_id",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )

    passenger_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("passengers.id"),
        nullable=False,
    )

    booking_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("bookings.id"),
        nullable=False,
    )

    booking: Mapped["Booking"] = relationship(
        back_populates="booking_passengers"
    )

    passenger: Mapped["Passenger"] = relationship(
        back_populates="booking_passengers"
    )


class Payment(Base):
    __tablename__ = "payments"

    __table_args__ = (
        UniqueConstraint(
            "provider",
            "provider_payment_id",
            name="uq_payment_provider_payment_id",
        ),
        Index(
            "ix_payments_booking_id",
            "booking_id",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )

    booking_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("bookings.id"),
        nullable=False,
    )

    provider: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
    )

    provider_payment_id: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
    )

    amount: Mapped[Decimal] = mapped_column(
        Numeric(12, 2),
        nullable=False,
    )

    currency: Mapped[str] = mapped_column(
        String(3),
        nullable=False,
    )

    status: Mapped[PaymentStatus] = mapped_column(
        SQLEnum(PaymentStatus),
        nullable=False,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    booking: Mapped["Booking"] = relationship(
        back_populates="payments"
    )

    events: Mapped[list["PaymentEvent"]] = relationship(
        back_populates="payment"
    )


class PaymentEvent(Base):
    __tablename__ = "payment_events"

    __table_args__ = (
        UniqueConstraint(
            "provider",
            "provider_event_id",
            name="uq_payment_event_provider_event_id",
        ),
        Index(
            "ix_payment_events_payment_id",
            "payment_id",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )

    payment_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("payments.id"),
        nullable=False,
    )

    provider: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
    )

    event_type: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
    )

    provider_event_id: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
    )

    status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
    )

    raw_payload: Mapped[dict] = mapped_column(
        JSONB,
        nullable=False,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )

    payment: Mapped["Payment"] = relationship(
        back_populates="events"
    )