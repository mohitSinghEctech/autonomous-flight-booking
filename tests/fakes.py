"""
Fakes for the things we don't own: the LLM, Duffel, Cashfree and the MCP search.

They are the offline providers from app/providers/offline.py (the same code PROVIDER_MODE=offline
runs), with two test tweaks: a fixed set of three DEL -> DXB offers, and payments that stay
`created` until a test says otherwise.

Everything else in the tests is real: FastAPI, uvicorn, SSE, LangGraph,
the services, the repositories and PostgreSQL.
"""
from datetime import date, timedelta

from app.models import PaymentStatus
from app.providers import offline
from app.providers.offline import (
    OfflineFlightProvider,
    OfflineLLM,
    OfflineMCPClient,
    OfflinePaymentProvider,
    make_offer,
)


WEBHOOK_SECRET = "test-webhook-secret"


class FakeFlightProvider(OfflineFlightProvider):
    """Three fixed offers (off_test_0..2); every search returns all of them."""

    def __init__(self):
        super().__init__()
        day = (date.today() + timedelta(days=30)).isoformat()
        for offer in [
            make_offer(0, 120.00, f"{day}T06:00"),
            make_offer(1, 96.50, f"{day}T09:30"),
            make_offer(2, 140.00, f"{day}T18:15"),
        ]:
            self.offers[offer.flight_id] = offer

    async def search_flights(self, request):
        return list(self.offers.values())


class FakePaymentProvider(OfflinePaymentProvider):
    """Orders stay `created` until a test sets `statuses[order_id]`."""

    def __init__(self):
        super().__init__(default_status=PaymentStatus.CREATED, secret=WEBHOOK_SECRET)


FakeMCPClient = OfflineMCPClient
FakeLLM = OfflineLLM


def sign_webhook(raw_body: bytes, timestamp: str, secret: str = WEBHOOK_SECRET) -> str:
    return offline.sign_webhook(raw_body, timestamp, secret)
