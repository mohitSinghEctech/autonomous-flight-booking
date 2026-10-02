from abc import ABC, abstractmethod

from app.models import PaymentResult


class PaymentProvider(ABC):
    @abstractmethod
    async def create_payment(self, booking_id: str, amount: float, currency: str) -> PaymentResult:
        pass
    
    @abstractmethod
    async def complete_payment(self, payment_id: str, amount: float, currency: str) -> PaymentResult:
        pass