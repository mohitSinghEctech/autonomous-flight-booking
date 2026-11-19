"""PROVIDER_MODE=offline: the whole flow runs on the offline providers, with no internet."""
import pytest

from app.main import check_config
from app.providers import all_providers, offline
from app.agent import handlers, llm
from app.core.settings import settings


@pytest.fixture
def fakes(monkeypatch):
    """Overrides conftest's fakes: the real offline providers, not the test-tuned ones."""
    monkeypatch.setattr(settings, "provider_mode", "offline")
    flights, payments = all_providers.build_providers()
    model = offline.OfflineLLM()

    monkeypatch.setattr(all_providers, "flight_provider", flights)
    monkeypatch.setattr(all_providers, "payment_provider", payments)
    monkeypatch.setattr(handlers, "flight_mcp_client", offline.OfflineMCPClient(flights))
    monkeypatch.setattr(llm, "client", model)

    class Bag:
        pass

    bag = Bag()
    bag.flights, bag.payments, bag.llm = flights, payments, model
    return bag


def test_offline_mode_builds_offline_providers(monkeypatch):
    monkeypatch.setattr(settings, "provider_mode", "offline")
    flights, payments = all_providers.build_providers()
    assert isinstance(flights, offline.OfflineFlightProvider)
    assert isinstance(payments, offline.OfflinePaymentProvider)


def test_offline_mode_needs_no_api_keys(monkeypatch):
    monkeypatch.setattr(settings, "provider_mode", "offline")
    monkeypatch.setattr(settings, "auth_mode", "demo")
    for name in ["llm_api_key", "llm_model", "flight_vendor_token", "cashfree_app_id", "cashfree_api_key"]:
        monkeypatch.setattr(settings, name, "")
    check_config()


def test_offline_mode_refuses_firebase_auth(monkeypatch):
    monkeypatch.setattr(settings, "provider_mode", "offline")
    monkeypatch.setattr(settings, "auth_mode", "firebase")
    monkeypatch.setattr(settings, "firebase_auth_emulator_host", None)
    with pytest.raises(RuntimeError, match="AUTH_MODE=demo"):
        check_config()


def test_offline_llm_reads_route_date_and_passengers():
    request = offline.parse_search("Find flights from BOM to LHR on 2027-01-10 for 2 passengers")
    assert request == {"origin": "BOM", "destination": "LHR", "date": "2027-01-10", "passengers": 2, "cabin": "economy"}


async def test_offline_search_returns_offers_for_the_requested_route(fakes):
    raw = await fakes.flights.search_flights(
        offline.SearchFlights(origin="BOM", destination="LHR", date="2027-01-10", passengers=1, cabin="economy")
    )
    assert len(raw) == 3
    assert {f.origin.airport_code for f in raw} == {"BOM"}
    assert {f.destination.airport_code for f in raw} == {"LHR"}
    assert all(f.departure_datetime.date().isoformat() == "2027-01-10" for f in raw)


async def test_offline_flow_search_hold_pay_confirm(session, fakes):
    approval = await session.until_approval("Find flights from BOM to LHR on 2027-01-10 for 1 passenger")
    start = session.stream.last_id
    assert (await session.approve(approval["approval_id"])).status_code == 202
    held = await session.stream.wait_for("booking.updated", after=start, where=lambda d: d and d["lifecycle"] == "held")
    await session.stream.wait_for("turn.completed", after=start, where=lambda t: t["outcome"] == "completed")
    assert fakes.flights.booked == [fakes.flights.cheapest.flight_id]

    start = session.stream.last_id
    assert (await session.api.post(session.url("/payments"))).status_code == 202
    payment = (await session.stream.wait_for("payment.updated", after=start, where=lambda p: p is not None))["data"]
    assert payment["status"] == "created"
    assert payment["amount"] == held["data"]["total_amount"]

    start = session.stream.last_id
    assert (await session.api.post(session.url(f"/payments/{payment['payment_id']}/sync"))).status_code == 202
    await session.stream.wait_for("payment.updated", after=start, where=lambda p: p and p["status"] == "paid")
    confirmed = await session.stream.wait_for("booking.updated", after=start, where=lambda b: b["lifecycle"] == "confirmed")
    assert confirmed
    assert fakes.flights.paid_orders
