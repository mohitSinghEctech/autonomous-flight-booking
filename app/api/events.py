"""
The UI <-> API contract, as code.

Spec:   agent-console/docs/api-contract.md
Mirror: agent-console/public/flight/src/api/contract.js
Change all three together. Additive change -> bump minor. Breaking -> bump major.

Two things live here:
  - SSEEvent: one message on the wire (id / event / data)
  - Pydantic models: the exact shape of each event's data and each request body.
    progress.py validates through them before publishing, so a typo fails here,
    not in the browser.
"""
import json
from dataclasses import dataclass
from datetime import date
from typing import Any, Literal

from pydantic import BaseModel, Field


CONTRACT_VERSION = "1.1"


# ---- the wire format --------------------------------------------------------

@dataclass
class SSEEvent:
    event: str
    data: Any
    event_id: int | None = None

    def to_sse(self) -> str:
        lines = []

        if self.event_id is not None:
            lines.append(f"id: {self.event_id}")

        lines.append(f"event: {self.event}")
        # one line of compact JSON; datetimes etc. become strings
        lines.append("data: " + json.dumps(self.data, separators=(",", ":"), default=str))

        return "\n".join(lines) + "\n\n"


# ---- enums ------------------------------------------------------------------

Stage = Literal[
    "idle", "thinking", "searching", "loading_passengers",
    "pricing", "awaiting_approval", "booking", "payment", "error",
]

Lifecycle = Literal["held", "awaiting_payment", "confirmed", "cancelled", "expired"]

PaymentState = Literal["created", "pending", "paid", "failed", "expired"]

ErrorCode = Literal[
    "validation_error", "unauthenticated", "forbidden", "session_not_found",
    "turn_in_progress", "approval_not_pending", "approval_already_resolved",
    "flight_not_found", "no_active_booking", "booking_not_payable", "payment_not_found",
    "provider_unavailable", "provider_error", "rate_limited", "contract_mismatch", "internal_error",
]


# ---- value objects ------------------------------------------------------------

class PassengerView(BaseModel):
    id: str
    name: str


class AirportView(BaseModel):
    airport_code: str
    airport_name: str


class StopView(BaseModel):
    airport: AirportView
    arrival_datetime: str | None = None
    departure_datetime: str | None = None


class FlightView(BaseModel):
    flight_id: str
    flight_name: str
    origin: AirportView
    destination: AirportView
    departure_datetime: str        # LOCAL airport time, no offset
    arrival_datetime: str
    price: float                   # total for all passengers
    currency: str
    cabin: str
    duration_minutes: int | None = None
    expires_at: str | None = None
    stops: list[StopView] = []


class SearchQuery(BaseModel):
    origin: str
    destination: str
    date: str
    passengers: int
    cabin: str


class BookingView(BaseModel):
    booking_id: str                # PROVIDER id (Duffel ord_...)
    booking_reference: str
    lifecycle: Lifecycle
    total_amount: float
    currency: str
    payment_required_by: str | None = None
    flight_id: str
    passengers: list[PassengerView] = []


class Checkout(BaseModel):
    provider: Literal["cashfree", "mock"] = "cashfree"
    mode: Literal["sandbox", "production"]
    payment_session_id: str
    expires_at: str | None = None


class PaymentView(BaseModel):
    payment_id: str                # provider order id
    status: PaymentState
    amount: float
    currency: str
    checkout: Checkout | None = None
    failure_reason: str | None = None
    paid_at: str | None = None


# ---- event payloads -----------------------------------------------------------

class StatusEvent(BaseModel):
    busy: bool
    stage: Stage
    text: str


class TurnStartedEvent(BaseModel):
    turn_id: str
    title: str | None = None


class TurnCompletedEvent(BaseModel):
    turn_id: str
    outcome: Literal["completed", "interrupted", "failed"]


class StepEvent(BaseModel):
    id: str
    turn_id: str | None = None
    kind: Literal["llm", "tool", "provider", "db", "approval", "system"] | None = None
    tool: str | None = None
    title: str | None = None
    detail: str | None = None
    status: Literal["running", "waiting", "done", "failed", "skipped"] | None = None
    started_at: str | None = None
    ended_at: str | None = None


class MessageEvent(BaseModel):
    id: str
    role: Literal["user", "assistant", "system"]
    text: str
    created_at: str | None = None


class FlightsResultsEvent(BaseModel):
    search_id: str
    query: SearchQuery
    flights: list[FlightView]


class FlightSelectedEvent(BaseModel):
    flight_id: str
    by: Literal["ai", "user"]
    reason: str | None = None


class ApprovalRequiredEvent(BaseModel):
    approval_id: str
    kind: Literal["book", "change", "cancel"]
    flight_id: str
    flight: FlightView
    passengers: list[PassengerView]
    total_amount: float
    currency: str
    message: str
    expires_at: str | None = None


class ApprovalResolvedEvent(BaseModel):
    approval_id: str
    decision: Literal["approved", "rejected", "superseded", "expired"]


class PassengerRequiredEvent(BaseModel):
    """v1.1: the agent needs details for passengers that aren't saved yet."""
    request_id: str
    needed: int
    existing: list[PassengerView] = []
    fields: list[str]
    message: str


class PassengerResolvedEvent(BaseModel):
    request_id: str
    decision: Literal["provided", "cancelled", "superseded"]
    passengers: list[PassengerView] = []


class ErrorEvent(BaseModel):
    code: ErrorCode
    message: str
    recoverable: bool = True


# ---- request bodies -------------------------------------------------------------

class MessageIn(BaseModel):
    text: str = Field(min_length=1, max_length=2000)
    client_id: str = Field(min_length=4, max_length=64)


class ApprovalIn(BaseModel):
    decision: Literal["approved", "rejected"]


class FlightSelectionIn(BaseModel):
    flight_id: str


PASSENGER_FIELDS = ["title", "given_name", "family_name", "gender", "born_on", "email", "phone_number"]


class NewPassenger(BaseModel):
    title: Literal["mr", "ms", "mrs", "miss", "dr"]
    given_name: str = Field(min_length=1, max_length=100)
    family_name: str = Field(min_length=1, max_length=100)
    gender: Literal["m", "f"]
    born_on: date
    email: str = Field(pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$", max_length=255)
    phone_number: str = Field(pattern=r"^\+[1-9]\d{7,14}$")      # E.164, what Duffel accepts


class PassengersIn(BaseModel):
    decision: Literal["provided", "cancelled"] = "provided"
    passengers: list[NewPassenger] = []


class ErrorBody(BaseModel):
    code: ErrorCode
    message: str
    retryable: bool = False
