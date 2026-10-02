from app.models import PaymentResult, PaymentStatus
from .base import PaymentProvider


class MockPaymentProvider(PaymentProvider):
    
    def __init__(self):
        self.payments = {}

    async def create_payment(
        self,
        booking_id: str,
        amount: float,
        currency: str,
    ) -> PaymentResult:
        result = PaymentResult(
            payment_id=f"pay_{booking_id}",
            status=PaymentStatus.CREATED,
            amount=amount,
            currency=currency,
            payment_session_id=f"https://mock-payment.local/pay/{booking_id}",
        )
        
        self.payments[result.payment_id] = result
        return result
        
    async def complete_payment(
        self,
        payment_id: str,
        amount: float,
        currency: str,
    ) -> PaymentResult:
        
        payment = self.payments.get(payment_id)
        
        if payment is None:
            raise ValueError(f"Payment with ID {payment_id} not found.")
        
        payment.status = PaymentStatus.PAID
        return payment