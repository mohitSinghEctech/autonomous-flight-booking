import uuid
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Payment, PaymentEvent, PaymentStatus


class PaymentRepository:

    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_payment(
        self,
        payment_id: uuid.UUID,
    ) -> Payment | None:

        result = await self.session.execute(
            select(Payment)
            .where(Payment.id == payment_id)
        )

        return result.scalar_one_or_none()

    async def get_by_provider_payment_id(
        self,
        provider: str,
        provider_payment_id: str,
    ) -> Payment | None:

        result = await self.session.execute(
            select(Payment)
            .where(
                Payment.provider == provider,
                Payment.provider_payment_id == provider_payment_id,
            )
        )

        return result.scalar_one_or_none()

    async def get_booking_payments(
        self,
        booking_id: uuid.UUID,
    ) -> list[Payment]:

        result = await self.session.execute(
            select(Payment)
            .where(Payment.booking_id == booking_id)
            .order_by(Payment.created_at.desc())
        )

        return list(result.scalars().all())

    async def create_payment(
        self,
        booking_id: uuid.UUID,
        provider: str,
        provider_payment_id: str,
        payment_session_id: str,
        amount: Decimal,
        currency: str,
        status: PaymentStatus,
    ) -> Payment:

        payment = Payment(
            booking_id=booking_id,
            provider=provider,
            provider_payment_id=provider_payment_id,
            payment_session_id=payment_session_id,
            amount=amount,
            currency=currency,
            status=status,
        )

        self.session.add(payment)

        await self.session.flush()

        return payment

    async def update_status(
        self,
        payment_id: uuid.UUID,
        status: PaymentStatus,
    ) -> Payment | None:

        payment = await self.get_payment(payment_id)

        if payment is None:
            return None

        payment.status = status

        await self.session.flush()

        return payment

    async def create_event(
        self,
        payment_id: uuid.UUID,
        provider: str,
        event_type: str,
        provider_event_id: str,
        status: str,
        raw_payload: dict,
    ) -> PaymentEvent:

        event = PaymentEvent(
            payment_id=payment_id,
            provider=provider,
            event_type=event_type,
            provider_event_id=provider_event_id,
            status=status,
            raw_payload=raw_payload,
        )

        self.session.add(event)

        await self.session.flush()

        return event
    
    async def get_latest_for_booking(
        self,
        booking_id: uuid.UUID,
    ) -> Payment | None:

        result = await self.session.execute(
            select(Payment)
            .where(Payment.booking_id == booking_id)
            .order_by(Payment.created_at.desc())
            .limit(1)
        )

        return result.scalars().first()

    async def reset_for_retry(
        self,
        payment: Payment,
        provider_payment_id: str,
        payment_session_id: str | None,
        amount: Decimal,
        currency: str,
    ) -> Payment:
        """One payment row per booking (uq_payment_booking_id): a retry reuses it
        with the NEW provider order id."""

        payment.provider_payment_id = provider_payment_id
        payment.payment_session_id = payment_session_id
        payment.amount = amount
        payment.currency = currency
        payment.status = PaymentStatus.CREATED

        await self.session.flush()

        return payment

    async def event_exists(
        self,
        provider: str,
        provider_event_id: str,
    ) -> bool:

        result = await self.session.execute(
            select(PaymentEvent.id)
            .where(
                PaymentEvent.provider == provider,
                PaymentEvent.provider_event_id == provider_event_id,
            )
        )

        return result.first() is not None
