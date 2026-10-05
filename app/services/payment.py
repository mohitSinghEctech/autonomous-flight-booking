import uuid
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError
from app.db.models import Booking, BookingStatus, Payment, PaymentStatus
from app.db.repositories.bookings import BookingRepository
from app.db.repositories.payments import PaymentRepository
from app.providers.all_providers import payment_provider as default_payment_provider
from app.providers.payment.base import PaymentProvider


PAYMENT_PROVIDER_NAME = "cashfree"


class PaymentService:
    """
    Owns the payment workflow and the booking lifecycle it drives:
    HELD -> AWAITING_PAYMENT (payment created) -> CONFIRMED (payment paid).
    """

    def __init__(
        self,
        session: AsyncSession,
        payment_provider: PaymentProvider = default_payment_provider,
    ):
        self.session = session
        self.payment_provider = payment_provider

        self.payment_repository = PaymentRepository(session)
        self.booking_repository = BookingRepository(session)

    async def create_payment(
        self,
        user_id: uuid.UUID,
        booking_id: uuid.UUID,
    ) -> tuple[Payment, Booking]:

        booking = await self._get_user_booking(user_id, booking_id)

        if booking.status != BookingStatus.HELD:
            raise AppError("Payment can only be created for a held booking.")
        
        # Check if payment already exists
        existing_payment = (
            await self.payment_provider.get_active_payment_for_booking(booking.id)
        )
        
        if existing_payment is not None:
            return (existing_payment, booking)

        # Our database booking ID is the order ID at the payment provider
        result = await self.payment_provider.create_payment(
            booking_id=str(booking.id),
            amount=float(booking.total_amount),
            currency=booking.currency,
        )

        payment = await self.payment_repository.create_payment(
            booking_id=booking.id,
            provider=PAYMENT_PROVIDER_NAME,
            provider_payment_id=result.payment_id,
            amount=Decimal(str(result.amount)),
            currency=result.currency,
            status=PaymentStatus(result.status.value),
        )

        await self.booking_repository.update_status(
            booking.id,
            BookingStatus.AWAITING_PAYMENT,
        )

        await self.session.commit()

        return payment, booking

    async def complete_payment(
        self,
        user_id: uuid.UUID,
        booking_id: uuid.UUID,
    ) -> tuple[Payment, Booking]:

        booking = await self._get_user_booking(user_id, booking_id)

        payments = await self.payment_repository.get_booking_payments(
            booking.id
        )

        if not payments:
            raise AppError("No payment has been created for this booking.")

        payment = payments[0]  # newest first
        
        # Return if already paid
        if payment.status == PaymentStatus.PAID:
            return payment, booking

        result = await self.payment_provider.complete_payment(
            payment.provider_payment_id,
            float(payment.amount),
            payment.currency,
        )
        
        new_status = PaymentStatus(result.status.value)

        await self.payment_repository.update_status(
            payment.id,
            new_status,
        )

        if new_status == PaymentStatus.PAID:
            await self.booking_repository.update_status(
                booking.id,
                BookingStatus.CONFIRMED,
            )

        await self.session.commit()

        return payment, booking

    async def _get_user_booking(
        self,
        user_id: uuid.UUID,
        booking_id: uuid.UUID,
    ) -> Booking:

        booking = await self.booking_repository.get_booking(booking_id)

        if booking is None or booking.user_id != user_id:
            raise AppError("Booking not found.")

        return booking
