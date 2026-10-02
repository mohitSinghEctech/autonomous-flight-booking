import os
import httpx

from app.models import PaymentResult, PaymentStatus
from .base import PaymentProvider
from dotenv import load_dotenv

load_dotenv()


class CashfreePaymentProvider(PaymentProvider):

    def __init__(self):
        self.app_id = os.getenv("CASHFREE_APP_ID")
        self.api_key = os.getenv("CASHFREE_API_KEY")
        self.environment = os.getenv("CASHFREE_ENV", "sandbox")

    async def create_payment(
        self,
        booking_id: str,
        amount: float,
        currency: str,
    ) -> PaymentResult:

        base_url = (
            "https://sandbox.cashfree.com"
            if self.environment == "sandbox"
            else "https://api.cashfree.com"
        )

        headers = {
            "x-client-id": self.app_id,
            "x-client-secret": self.api_key,
            "x-api-version": "2025-01-01",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

        payload = {
            "order_id": booking_id,
            "order_amount": amount,
            "order_currency": currency,
            "customer_details": {
                "customer_id": booking_id,
                "customer_phone": "9999999999",
            },
        }

        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{base_url}/pg/orders",
                headers=headers,
                json=payload,
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

        base_url = (
            "https://sandbox.cashfree.com"
            if self.environment == "sandbox"
            else "https://api.cashfree.com"
        )

        headers = {
            "x-client-id": self.app_id,
            "x-client-secret": self.api_key,
            "x-api-version": "2025-01-01",
            "Accept": "application/json",
        }

        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{base_url}/pg/orders/{payment_id}/payments",
                headers=headers,
            )

        response.raise_for_status()

        payments = response.json()

        if not payments:
            return PaymentResult(
                payment_id=payment_id,
                status=PaymentStatus.PENDING,
                amount=amount,
                currency=currency,
            )

        payment = payments[0]

        status = payment["payment_status"]

        if status == "SUCCESS":
            payment_status = PaymentStatus.PAID
        elif status == "PENDING":
            payment_status = PaymentStatus.PENDING
        else:
            payment_status = PaymentStatus.FAILED

        return PaymentResult(
            payment_id=payment_id,
            status=payment_status,
            amount=payment["payment_amount"],
            currency=payment["payment_currency"],
        )