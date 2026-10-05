import uuid
from abc import ABC, abstractmethod

from app.models import PaymentResult
from app.db.models import Payment


class PaymentProvider(ABC):
    @abstractmethod
    async def create_payment(self, booking_id: str, amount: float, currency: str) -> PaymentResult:
        pass
    
    @abstractmethod
    async def complete_payment(self, payment_id: str, amount: float, currency: str) -> PaymentResult:
        pass
    
    @abstractmethod
    async def get_active_payment_for_booking(self, booking_id: uuid.UUID) -> Payment | None:
        pass