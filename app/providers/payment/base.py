from abc import ABC, abstractmethod

from app.models import PaymentResult


class PaymentProvider(ABC):
    @property
    def mode(self) -> str:
        """'sandbox' or 'production' — the browser checkout needs to know."""
        return "sandbox"

    def verify_webhook(self, raw_body: bytes, timestamp: str, signature: str) -> bool:
        """Providers that send webhooks override this. Default: trust nothing."""
        return False

    @abstractmethod
    async def create_payment(self, booking_id: str, amount: float, currency: str) -> PaymentResult:
        """booking_id is used as the provider's order id (must be unique per attempt)."""
        pass

    @abstractmethod
    async def complete_payment(self, payment_id: str, amount: float, currency: str) -> PaymentResult:
        """Ask the provider for the CURRENT status of an order (no money moves here)."""
        pass
