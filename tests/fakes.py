"""
Fakes for the three things we don't own: the LLM, Duffel, Cashfree.

Everything else in the tests is real: FastAPI, uvicorn, SSE, LangGraph,
the services, the repositories and PostgreSQL.
"""
import base64
import hashlib
import hmac
import json
import re
import uuid
from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace

from app.models import (
    Airport,
    BookingResult,
    Cabin,
    Flight,
    PaymentResult,
    PaymentStatus,
)
from app.providers.flights.base import FlightProvider
from app.providers.payment.base import PaymentProvider


WEBHOOK_SECRET = "test-webhook-secret"


def make_offer(i: int, price: float, departs: str) -> Flight:
    return Flight(
        flight_id=f"off_test_{i}",
        provider_reference=f"off_test_{i}",
        flight_name=["Duffel Airways", "Emirates", "IndiGo"][i % 3],
        origin=Airport(airport_code="DEL", airport_name="Indira Gandhi International"),
        destination=Airport(airport_code="DXB", airport_name="Dubai International"),
        departure_datetime=f"{departs}:00",
        arrival_datetime=f"{departs[:11]}23:00:00",
        price=price,
        currency="GBP",
        cabin=Cabin.ECONOMY,
        duration_minutes=210,
        stops=[],
    )


class FakeFlightProvider(FlightProvider):

    def __init__(self):
        day = (date.today() + timedelta(days=30)).isoformat()
        self.offers = {
            offer.flight_id: offer
            for offer in [
                make_offer(0, 120.00, f"{day}T06:00"),
                make_offer(1, 96.50, f"{day}T09:30"),      # cheapest
                make_offer(2, 140.00, f"{day}T18:15"),
            ]
        }
        self.booked: list[str] = []
        self.cancelled: list[str] = []

    @property
    def cheapest(self) -> Flight:
        return min(self.offers.values(), key=lambda f: f.price)

    async def search_flights(self, request):
        return list(self.offers.values())

    async def fetch_flight_details(self, flight_id):
        return self.offers.get(flight_id)

    async def book_flight(self, request, flight, passengers):
        self.booked.append(flight.flight_id)
        n = len(self.booked)
        return BookingResult(
            booking_id=f"ord_fake_{uuid.uuid4().hex[:8]}",
            booking_reference=f"FK{uuid.uuid4().hex[:4].upper()}",
            status="hold",
            total_amount=flight.price,
            currency=flight.currency,
            payment_required_by=datetime.now(timezone.utc) + timedelta(days=2 + n),
        )

    async def cancel_order(self, provider_booking_id):
        self.cancelled.append(provider_booking_id)


class FakePaymentProvider(PaymentProvider):
    """Cashfree stand-in. `statuses` is what the provider would answer for an order."""

    def __init__(self):
        self.created: list[str] = []
        self.statuses: dict[str, PaymentStatus] = {}

    async def create_payment(self, booking_id, amount, currency):
        self.created.append(booking_id)
        return PaymentResult(
            payment_id=booking_id,
            status=PaymentStatus.CREATED,
            amount=amount,
            currency=currency,
            payment_session_id=f"session_{booking_id[:12]}",
        )

    async def complete_payment(self, payment_id, amount, currency):
        return PaymentResult(
            payment_id=payment_id,
            status=self.statuses.get(payment_id, PaymentStatus.CREATED),
            amount=amount,
            currency=currency,
        )

    def verify_webhook(self, raw_body, timestamp, signature):
        return hmac.compare_digest(sign_webhook(raw_body, timestamp), signature)


def sign_webhook(raw_body: bytes, timestamp: str, secret: str = WEBHOOK_SECRET) -> str:
    digest = hmac.new(secret.encode(), timestamp.encode() + raw_body, hashlib.sha256).digest()
    return base64.b64encode(digest).decode()


class FakeMCPClient:
    """handlers.py searches through MCP; this answers with the fake offers."""

    def __init__(self, flights: FakeFlightProvider):
        self.flights = flights

    async def search_flights(self, **kwargs):
        return json.dumps([f.model_dump(mode="json") for f in self.flights.offers.values()])


# ---- a rule-based fake LLM -------------------------------------------------------------

class FakeLLM:
    """
    Behaves like a well-prompted model, deterministically:
      user asks to find flights -> search_flights -> get_saved_passengers
        -> request_passenger_details (if not enough complete passengers) -> book_flight (cheapest)
      user names a flight_id   -> get_saved_passengers -> book_flight (that flight)
      tool replies             -> short text
    """

    def __init__(self):
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self.create))
        self.calls = 0

    async def create(self, model=None, messages=None, tools=None, **kwargs):
        self.calls += 1
        reply = decide(messages)
        return SimpleNamespace(choices=[SimpleNamespace(message=_Message(**reply))])


class _Message:
    def __init__(self, content=None, tool_calls=None):
        self.content = content
        self.tool_calls = tool_calls

    def model_dump(self):
        return {"role": "assistant", "content": self.content, "tool_calls": self.tool_calls}


def call(name: str, **arguments) -> dict:
    return {"tool_calls": [{
        "id": f"call_{uuid.uuid4().hex[:8]}",
        "type": "function",
        "function": {"name": name, "arguments": json.dumps(arguments)},
    }]}


def decide(messages: list[dict]) -> dict:
    last = messages[-1]

    if last["role"] == "user":
        text = last["content"]
        if "flight_id" in text:
            return call("get_saved_passengers")
        if re.search(r"\b(find|search|flights?)\b", text, re.I):
            pax = int((re.search(r"(\d+)\s+passenger", text) or [None, 1])[1])
            day = (date.today() + timedelta(days=30)).isoformat()
            return call("search_flights", origin="DEL", destination="DXB", date=day, passengers=pax, cabin="economy")
        return {"content": "Hello! Where would you like to fly?"}

    if last["role"] != "tool":
        return {"content": "Okay."}

    name = tool_name_for(messages, last["tool_call_id"])
    content = json.loads(last["content"])

    if name == "search_flights":
        return call("get_saved_passengers")

    if name in ("get_saved_passengers", "request_passenger_details"):
        if isinstance(content, dict) and "error" in content:
            return {"content": "No problem — tell me when you want to continue."}

        saved = latest_tool_result(messages, "get_saved_passengers") or []
        added = (content.get("added_passengers", []) if isinstance(content, dict) else [])
        ids = [p["id"] for p in saved if not p["missing_details"]] + [p["id"] for p in added]
        needed = passengers_needed(messages)

        if len(ids) < needed:
            return call("request_passenger_details", count=needed - len(ids), reason="I need one more traveller.")

        return call("book_flight", flight_id=chosen_flight(messages), passenger_ids=ids[:needed])

    if name == "book_flight":
        if isinstance(content, dict) and "error" in content:
            return {"content": "Okay, I did not book it."}
        return {"content": "Your seat is held."}

    return {"content": "Done."}


def tool_name_for(messages, tool_call_id):
    for m in messages:
        for tc in (m.get("tool_calls") or []):
            if tc["id"] == tool_call_id:
                return tc["function"]["name"]
    return None


def latest_tool_result(messages, name):
    for m in reversed(messages):
        if m.get("role") == "tool" and tool_name_for(messages, m["tool_call_id"]) == name:
            return json.loads(m["content"])
    return None


def passengers_needed(messages) -> int:
    for m in reversed(messages):
        for tc in (m.get("tool_calls") or []):
            if tc["function"]["name"] == "search_flights":
                return json.loads(tc["function"]["arguments"])["passengers"]
    return 1


def chosen_flight(messages) -> str:
    for m in reversed(messages):
        if m.get("role") == "user":
            match = re.search(r"flight_id (\S+)", m["content"] or "")
            if match:
                return match.group(1)
            break
    flights = latest_tool_result(messages, "search_flights") or []
    return min(flights, key=lambda f: f["price"])["flight_id"]
