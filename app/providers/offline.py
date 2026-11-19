"""
Offline stand-ins for the four internet services: the LLM, Duffel, Cashfree and the MCP search.

PROVIDER_MODE=offline wires these in (see all_providers.py, agent/llm.py, agent/handlers.py),
so the whole flow (chat -> search -> approval -> passengers -> hold -> pay -> confirmed)
runs with no network. Everything else stays real: FastAPI, LangGraph, the services and Postgres.

The tests use the same classes (tests/fakes.py), so offline mode and the tests cannot drift apart.
"""
import base64
import hashlib
import hmac
import json
import re
import uuid
from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace

from app.core.errors import OfferUnavailable, ProviderError
from app.models import (
    Airport,
    BookingResult,
    Cabin,
    Flight,
    PaymentResult,
    PaymentStatus,
    SearchFlights,
)
from app.providers.flights.base import FlightProvider
from app.providers.payment.base import PaymentProvider


WEBHOOK_SECRET = "offline-webhook-secret"

AIRLINES = ["Duffel Airways", "Emirates", "IndiGo"]

# (hour, minute, price) for the three offers generated per search
SCHEDULE = [(6, 0, 120.00), (9, 30, 96.50), (18, 15, 140.00)]


def make_offer(
    i: int,
    price: float,
    departs: str,
    origin: str = "DEL",
    destination: str = "DXB",
    cabin: Cabin = Cabin.ECONOMY,
    flight_id: str | None = None,
) -> Flight:
    flight_id = flight_id or f"off_test_{i}"
    return Flight(
        flight_id=flight_id,
        provider_reference=flight_id,
        flight_name=AIRLINES[i % 3],
        origin=Airport(airport_code=origin, airport_name=f"{origin} Airport"),
        destination=Airport(airport_code=destination, airport_name=f"{destination} Airport"),
        departure_datetime=f"{departs}:00",
        arrival_datetime=f"{departs[:11]}23:00:00",
        price=price,
        currency="GBP",
        cabin=cabin,
        duration_minutes=210,
        stops=[],
    )


class OfflineFlightProvider(FlightProvider):
    """Duffel stand-in. Every search creates three offers for the requested route and day."""

    def __init__(self):
        self.offers: dict[str, Flight] = {}
        self.booked: list[str] = []
        self.attempts: list[str] = []
        self.gone: set[str] = set()
        self.cancelled: list[str] = []
        self.paid_orders: list[str] = []
        self.fail_payment = False

    @property
    def cheapest(self) -> Flight:
        return min(self.offers.values(), key=lambda f: f.price)

    async def search_flights(self, request: SearchFlights) -> list[Flight]:
        day = request.date.isoformat()
        found = []
        for i, (hour, minute, price) in enumerate(SCHEDULE):
            offer = make_offer(
                i,
                price,
                f"{day}T{hour:02d}:{minute:02d}",
                origin=request.origin,
                destination=request.destination,
                cabin=request.cabin,
                flight_id=f"off_{uuid.uuid4().hex[:10]}",
            )
            self.offers[offer.flight_id] = offer
            found.append(offer)
        return found

    async def fetch_flight_details(self, flight_id):
        return self.offers.get(flight_id)

    async def book_flight(self, request, flight, passengers):
        self.attempts.append(flight.flight_id)
        if flight.flight_id in self.gone:
            raise OfferUnavailable(flight.flight_id)
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

    async def pay_order(self, provider_booking_id, amount, currency):
        self.paid_orders.append(provider_booking_id)
        if self.fail_payment:
            raise ProviderError("Airline rejected the payment.")


class OfflinePaymentProvider(PaymentProvider):
    """
    Cashfree stand-in. `statuses` is what the provider would answer for an order;
    an order not in it answers `default_status`. Offline mode uses PAID, so a sync
    after creating a payment confirms the booking (there is no checkout page offline).
    """

    def __init__(self, default_status: PaymentStatus = PaymentStatus.PAID, secret: str = WEBHOOK_SECRET):
        self.created: list[str] = []
        self.statuses: dict[str, PaymentStatus] = {}
        self.default_status = default_status
        self.secret = secret

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
            status=self.statuses.get(payment_id, self.default_status),
            amount=amount,
            currency=currency,
        )

    def verify_webhook(self, raw_body, timestamp, signature):
        return hmac.compare_digest(sign_webhook(raw_body, timestamp, self.secret), signature)


def sign_webhook(raw_body: bytes, timestamp: str, secret: str = WEBHOOK_SECRET) -> str:
    digest = hmac.new(secret.encode(), timestamp.encode() + raw_body, hashlib.sha256).digest()
    return base64.b64encode(digest).decode()


class OfflineMCPClient:
    """handlers.py searches through MCP; offline it asks the offline flight provider directly."""

    connected = True

    def __init__(self, flights: FlightProvider):
        self.flights = flights

    async def start(self):
        pass

    async def stop(self):
        pass

    async def search_flights(self, origin, destination, date, passengers, cabin):
        request = SearchFlights(origin=origin, destination=destination, date=date, passengers=passengers, cabin=cabin)
        found = await self.flights.search_flights(request)
        return json.dumps([f.model_dump(mode="json") for f in found])


class OfflineLLM:
    """
    Behaves like a well-prompted model, deterministically (same interface as AsyncOpenAI):
      "find flights from BOM to LHR on 2027-01-10 for 2 passengers"
                              -> search_flights -> get_saved_passengers
        -> request_passenger_details (if not enough complete passengers) -> book_flight (cheapest)
      user names a flight_id  -> get_saved_passengers -> book_flight (that flight)
      tool replies            -> short text
    Route defaults to DEL -> DXB and the date to 30 days from today.
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


def parse_search(text: str) -> dict:
    route = re.search(r"\bfrom\s+([A-Z]{3})\s+to\s+([A-Z]{3})\b", text)
    day = re.search(r"\b(\d{4}-\d{2}-\d{2})\b", text)
    pax = re.search(r"(\d+)\s+passenger", text)
    return {
        "origin": route[1] if route else "DEL",
        "destination": route[2] if route else "DXB",
        "date": day[1] if day else (date.today() + timedelta(days=30)).isoformat(),
        "passengers": int(pax[1]) if pax else 1,
        "cabin": "economy",
    }


def decide(messages: list[dict]) -> dict:
    last = messages[-1]

    if last["role"] == "user":
        text = last["content"]
        if "flight_id" in text:
            return call("get_saved_passengers")
        if re.search(r"\b(find|search|flights?)\b", text, re.I):
            return call("search_flights", **parse_search(text))
        return {"content": "Hello! Where would you like to fly?"}

    if last["role"] != "tool":
        return {"content": "Okay."}

    name = tool_name_for(messages, last["tool_call_id"])
    content = json.loads(last["content"])

    if name == "search_flights":
        if isinstance(content, dict) and "error" in content:
            return {"content": f"Sorry, I couldn't search flights: {content['error']}"}
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
    result = latest_tool_result(messages, "search_flights") or {}
    flights = result.get("flights", result) if isinstance(result, dict) else result
    return min(flights, key=lambda f: f["price"])["flight_id"]
