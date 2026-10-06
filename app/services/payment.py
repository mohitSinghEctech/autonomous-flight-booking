import secrets
import uuid
from decimal import Decimal

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError, BookingNotPayable, PaymentNotFound
from app.db.models import Booking, BookingStatus, Payment, PaymentStatus
from app.db.repositories.bookings import BookingRepository
from app.db.repositories.payments import PaymentRepository
from app.models import PaymentStatus as ProviderPaymentStatus
from app.providers import all_providers
from app.providers.payment.base import PaymentProvider


PAYMENT_PROVIDER_NAME = "cashfree"

OPEN_STATUSES = {PaymentStatus.CREATED, PaymentStatus.PENDING}

# Which payment status may move to which. PAID is terminal: nothing moves it back.
ALLOWED = {
    PaymentStatus.CREATED: {PaymentStatus.PENDING, PaymentStatus.PAID, PaymentStatus.FAILED, PaymentStatus.EXPIRED},
    PaymentStatus.PENDING: {PaymentStatus.PAID, PaymentStatus.FAILED, PaymentStatus.EXPIRED},
    PaymentStatus.FAILED: {PaymentStatus.PAID},      # a late success still wins
    PaymentStatus.EXPIRED: {PaymentStatus.PAID},
    PaymentStatus.PAID: set(),
}


class PaymentService:
    """
    Owns the payment workflow and the booking lifecycle it drives:

        HELD -> AWAITING_PAYMENT (payment created) -> CONFIRMED (payment paid)

    Two rules:
      - create_payment is idempotent: an open payment is reused, never duplicated.
      - only the PROVIDER's answer (webhook or sync) moves a payment to paid/failed,
        and every such answer goes through apply_provider_status().
    """

    def __init__(
        self,
        session: AsyncSession,
        payment_provider: PaymentProvider | None = None,
    ):
        self.session = session
        # looked up at call time, so tests can swap all_providers.payment_provider
        self.payment_provider = payment_provider or all_providers.payment_provider

        self.payment_repository = PaymentRepository(session)
        self.booking_repository = BookingRepository(session)

    # ---- create -------------------------------------------------------------

    async def create_payment(
        self,
        user_id: uuid.UUID,
        booking_id: uuid.UUID,
    ) -> tuple[Payment, Booking]:

        booking = await self._get_user_booking(user_id, booking_id)

        if booking.status not in (BookingStatus.HELD, BookingStatus.AWAITING_PAYMENT):
            raise BookingNotPayable(f"This booking can't be paid (status: {booking.status.value}).")

        payment = await self.payment_repository.get_latest_for_booking(booking.id)

        # 1. Idempotent: an open payment is the answer, not a new one.
        if payment is not None and payment.status in OPEN_STATUSES:
            return payment, booking

        if payment is not None and payment.status == PaymentStatus.PAID:
            raise BookingNotPayable("This booking is already paid.")

        # 2. First attempt: order id = booking id. Retry: provider order ids must be
        #    unique, so add a short suffix.
        order_id = str(booking.id) if payment is None else f"{booking.id}-{secrets.token_hex(3)}"

        result = await self.payment_provider.create_payment(
            booking_id=order_id,
            amount=float(booking.total_amount),
            currency=booking.currency,
        )

        if payment is None:
            payment = await self.payment_repository.create_payment(
                booking_id=booking.id,
                provider=PAYMENT_PROVIDER_NAME,
                provider_payment_id=result.payment_id,
                payment_session_id=result.payment_session_id,
                amount=Decimal(str(result.amount)),
                currency=result.currency,
                status=PaymentStatus.CREATED,
            )
        else:
            payment = await self.payment_repository.reset_for_retry(
                payment,
                provider_payment_id=result.payment_id,
                payment_session_id=result.payment_session_id,
                amount=Decimal(str(result.amount)),
                currency=result.currency,
            )

        await self.booking_repository.update_status(
            booking.id,
            BookingStatus.AWAITING_PAYMENT,
        )

        await self.session.commit()

        return payment, booking

    # ---- read the provider (fallback when no webhook arrives) ----------------

    async def sync_payment(
        self,
        user_id: uuid.UUID,
        booking_id: uuid.UUID,
    ) -> tuple[Payment, Booking, bool]:

        booking = await self._get_user_booking(user_id, booking_id)
        payment = await self.payment_repository.get_latest_for_booking(booking.id)

        if payment is None:
            raise PaymentNotFound("No payment has been created for this booking.")

        if payment.status == PaymentStatus.PAID:
            return payment, booking, False

        result = await self.payment_provider.complete_payment(
            payment.provider_payment_id,
            float(payment.amount),
            payment.currency,
        )

        changed = await self._transition(payment, booking, result.status)
        await self.session.commit()

        return payment, booking, changed

    # kept for the LLM tool `complete_payment`
    async def complete_payment(self, user_id: uuid.UUID, booking_id: uuid.UUID) -> tuple[Payment, Booking]:
        payment, booking, _ = await self.sync_payment(user_id, booking_id)
        return payment, booking

    # ---- the ONE place a provider result is applied ---------------------------

    async def apply_provider_status(
        self,
        provider_payment_id: str,
        status: ProviderPaymentStatus,
        *,
        event_id: str | None = None,
        event_type: str = "sync",
        raw_payload: dict | None = None,
    ) -> tuple[Payment, Booking, bool, bool]:
        """
        Used by the webhook. Returns (payment, booking, changed, duplicate).
        Idempotent twice over:
          - the same provider event (provider, event_id) is stored once -> duplicate=True
          - a status that is not a legal move (e.g. PAID -> FAILED) changes nothing
        """
        payment = await self.payment_repository.get_by_provider_payment_id(
            PAYMENT_PROVIDER_NAME,
            provider_payment_id,
        )

        if payment is None:
            raise PaymentNotFound(f"Unknown payment {provider_payment_id}.")

        booking = await self.booking_repository.get_booking(payment.booking_id)

        if event_id is not None:
            if await self.payment_repository.event_exists(PAYMENT_PROVIDER_NAME, event_id):
                return payment, booking, False, True

            try:
                await self.payment_repository.create_event(
                    payment_id=payment.id,
                    provider=PAYMENT_PROVIDER_NAME,
                    event_type=event_type,
                    provider_event_id=event_id,
                    status=status.value,
                    raw_payload=raw_payload or {},
                )
            except IntegrityError:
                # the same webhook raced in on another request: it was handled there
                await self.session.rollback()
                payment = await self.payment_repository.get_by_provider_payment_id(PAYMENT_PROVIDER_NAME, provider_payment_id)
                booking = await self.booking_repository.get_booking(payment.booking_id)
                return payment, booking, False, True

        changed = await self._transition(payment, booking, status)
        await self.session.commit()

        return payment, booking, changed, False

    async def _transition(
        self,
        payment: Payment,
        booking: Booking,
        provider_status: ProviderPaymentStatus,
    ) -> bool:

        new_status = PaymentStatus(provider_status.value)

        if new_status == payment.status or new_status not in ALLOWED[payment.status]:
            return False

        await self.payment_repository.update_status(payment.id, new_status)

        if new_status == PaymentStatus.PAID:
            await self.booking_repository.update_status(booking.id, BookingStatus.CONFIRMED)

        return True

    async def _get_user_booking(
        self,
        user_id: uuid.UUID,
        booking_id: uuid.UUID,
    ) -> Booking:

        booking = await self.booking_repository.get_booking(booking_id)

        if booking is None or booking.user_id != user_id:
            raise AppError("Booking not found.")

        return booking
