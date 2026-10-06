import base64
import hashlib
import hmac
import os

import httpx
from dotenv import load_dotenv

from app.models import PaymentResult, PaymentStatus
from .base import PaymentProvider

load_dotenv()


# Cashfree payment_status -> ours. Anything not listed counts as failed.
_STATUS = {
    "SUCCESS": PaymentStatus.PAID,
    "PENDING": PaymentStatus.PENDING,
    "NOT_ATTEMPTED": PaymentStatus.CREATED,
}


class CashfreePaymentProvider(PaymentProvider):

    API_VERSION = "2025-01-01"

    def __init__(self):
        self.app_id = os.getenv("CASHFREE_APP_ID")
        self.api_key = os.getenv("CASHFREE_API_KEY")
        self.environment = os.getenv("CASHFREE_ENV", "sandbox")
        # Public URL of POST /api/webhooks/cashfree (a tunnel when running locally).
        self.webhook_url = os.getenv("CASHFREE_WEBHOOK_URL")

    @property
    def mode(self) -> str:
        return "sandbox" if self.environment == "sandbox" else "production"

    @property
    def base_url(self) -> str:
        return (
            "https://sandbox.cashfree.com"
            if self.environment == "sandbox"
            else "https://api.cashfree.com"
        )

    def _headers(self) -> dict:
        return {
            "x-client-id": self.app_id,
            "x-client-secret": self.api_key,
            "x-api-version": self.API_VERSION,
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

    async def create_payment(
        self,
        booking_id: str,
        amount: float,
        currency: str,
    ) -> PaymentResult:

        payload = {
            "order_id": booking_id,
            "order_amount": amount,
            "order_currency": currency,
            "customer_details": {
                "customer_id": booking_id[:50],
                "customer_phone": "9999999999",
            },
        }

        if self.webhook_url:
            payload["order_meta"] = {"notify_url": self.webhook_url}

        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{self.base_url}/pg/orders",
                headers=self._headers(),
                json=payload,
                timeout=30,
            )

        response.raise_for_status()

        data = response.json()

        return PaymentResult(
            payment_id=data["order_id"],
            status=PaymentStatus.CREATED,
            amount=data["order_amount"],
            currency=data["order_currency"],
            payment_session_id=data["payment_session_id"],
        )

    async def complete_payment(
        self,
        payment_id: str,
        amount: float,
        currency: str,
    ) -> PaymentResult:
        """Read the order's payment attempts. No attempts yet -> still CREATED."""

        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{self.base_url}/pg/orders/{payment_id}/payments",
                headers=self._headers(),
                timeout=30,
            )

        response.raise_for_status()

        attempts = response.json()

        if not attempts:
            return PaymentResult(
                payment_id=payment_id,
                status=PaymentStatus.CREATED,
                amount=amount,
                currency=currency,
            )

        # One successful attempt is enough; otherwise the latest attempt decides.
        success = next((a for a in attempts if a.get("payment_status") == "SUCCESS"), None)
        attempt = success or attempts[0]

        return PaymentResult(
            payment_id=payment_id,
            status=to_payment_status(attempt.get("payment_status")),
            amount=attempt.get("payment_amount", amount),
            currency=attempt.get("payment_currency", currency),
        )

    # ---- webhooks ---------------------------------------------------------

    def verify_webhook(self, raw_body: bytes, timestamp: str, signature: str) -> bool:
        """Cashfree: signature = base64(HMAC-SHA256(secret_key, timestamp + raw_body))."""
        if not (self.api_key and timestamp and signature):
            return False

        digest = hmac.new(
            self.api_key.encode(),
            timestamp.encode() + raw_body,
            hashlib.sha256,
        ).digest()

        return hmac.compare_digest(base64.b64encode(digest).decode(), signature)


def to_payment_status(cashfree_status: str | None) -> PaymentStatus:
    return _STATUS.get((cashfree_status or "").upper(), PaymentStatus.FAILED)


def parse_webhook(payload: dict) -> dict:
    """
    Pull what we need out of a Cashfree payment webhook.
    Returns {order_id, status, event_id, event_type}.
    event_id is what we dedupe on: one row per (provider, event_id).
    """
    data = payload.get("data") or {}
    order = data.get("order") or {}
    payment = data.get("payment") or {}
    event_type = payload.get("type", "UNKNOWN")

    cf_payment_id = payment.get("cf_payment_id")
    event_id = f"{event_type}:{cf_payment_id or order.get('order_id')}"

    return {
        "order_id": order.get("order_id"),
        "status": to_payment_status(payment.get("payment_status")),
        "event_id": event_id,
        "event_type": event_type,
    }
