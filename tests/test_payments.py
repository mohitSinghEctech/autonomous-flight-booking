"""Payments: idempotent create, sync fallback, signed + idempotent webhook."""
import json
import random

from sqlalchemy import func, select

from app.db.models import Booking, BookingStatus, Payment, PaymentEvent, PaymentStatus
from app.db.session import SessionLocal
from app.models import PaymentStatus as ProviderStatus
from tests.fakes import sign_webhook


async def start_payment(session) -> dict:
    start = session.stream.last_id
    assert (await session.api.post(session.url("/payments"))).status_code == 202
    payment = (await session.stream.wait_for("payment.updated", after=start, where=lambda p: p is not None))["data"]
    await session.turn_done(after=start)
    return payment


async def booked_session(session):
    booking = await session.until_booked()
    await session.stream.wait_for("turn.completed", where=lambda t: t["outcome"] == "completed")
    return booking


def webhook_body(order_id: str, status: str = "SUCCESS", cf_payment_id: int | None = None) -> bytes:
    # Cashfree payment ids are globally unique, and so is our dedupe key
    cf_payment_id = cf_payment_id or random.randint(10**8, 10**9)
    return json.dumps({
        "type": "PAYMENT_SUCCESS_WEBHOOK" if status == "SUCCESS" else "PAYMENT_FAILED_WEBHOOK",
        "data": {"order": {"order_id": order_id}, "payment": {"cf_payment_id": cf_payment_id, "payment_status": status}},
    }).encode()


async def post_webhook(api, raw: bytes, signature: str | None = None):
    timestamp = "1760000000"
    return await api.post(
        "/api/webhooks/cashfree",
        content=raw,
        headers={
            "Content-Type": "application/json",
            "x-webhook-timestamp": timestamp,
            "x-webhook-signature": signature or sign_webhook(raw, timestamp),
        },
    )


async def test_create_payment_returns_a_checkout(session, fakes):
    booking = await booked_session(session)
    payment = await start_payment(session)

    assert payment["status"] == "created"
    assert payment["checkout"]["provider"] == "cashfree"
    assert payment["checkout"]["payment_session_id"].startswith("session_")
    assert payment["amount"] == booking["total_amount"]

    lifecycle = session.stream.of("booking.updated")[-1]["data"]["lifecycle"]
    assert lifecycle == "awaiting_payment"


async def test_create_payment_twice_reuses_the_open_order(session, fakes):
    await booked_session(session)
    first = await start_payment(session)
    second = await start_payment(session)

    assert first["payment_id"] == second["payment_id"]
    assert len(fakes.payments.created) == 1


async def test_payment_without_booking_is_409(session):
    response = await session.api.post(session.url("/payments"))
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "no_active_booking"


async def test_sync_confirms_when_the_provider_says_paid(session, fakes):
    await booked_session(session)
    payment = await start_payment(session)

    fakes.payments.statuses[payment["payment_id"]] = ProviderStatus.PAID
    start = session.stream.last_id
    assert (await session.api.post(session.url(f"/payments/{payment['payment_id']}/sync"))).status_code == 202

    paid = await session.stream.wait_for("payment.updated", after=start, where=lambda p: p and p["status"] == "paid")
    assert paid["data"]["checkout"] is None
    confirmed = await session.stream.wait_for("booking.updated", after=start, where=lambda b: b["lifecycle"] == "confirmed")
    assert confirmed


async def test_sync_while_unpaid_changes_nothing(session, fakes):
    await booked_session(session)
    payment = await start_payment(session)
    start = session.stream.last_id

    await session.api.post(session.url(f"/payments/{payment['payment_id']}/sync"))
    still = await session.stream.wait_for("payment.updated", after=start)
    assert still["data"]["status"] == "created"


async def test_webhook_confirms_and_is_idempotent(session, fakes, api):
    booking = await booked_session(session)
    payment = await start_payment(session)
    raw = webhook_body(payment["payment_id"])
    start = session.stream.last_id

    first = await post_webhook(api, raw)
    assert first.status_code == 200 and first.json()["duplicate"] is False
    await session.stream.wait_for("booking.updated", after=start, where=lambda b: b["lifecycle"] == "confirmed")

    again = await post_webhook(api, raw)                             # Cashfree retries
    assert again.status_code == 200 and again.json()["duplicate"] is True

    async with SessionLocal() as db:
        row = (await db.execute(select(Payment).where(Payment.provider_payment_id == payment["payment_id"]))).scalar_one()
        events = await db.scalar(select(func.count()).select_from(PaymentEvent).where(PaymentEvent.payment_id == row.id))
        status = (await db.execute(select(Booking.status).where(Booking.provider_booking_id == booking["booking_id"]))).scalar_one()

    assert row.status == PaymentStatus.PAID
    assert events == 1
    assert status == BookingStatus.CONFIRMED


async def test_webhook_with_a_bad_signature_is_401(session, fakes, api):
    await booked_session(session)
    payment = await start_payment(session)

    response = await post_webhook(api, webhook_body(payment["payment_id"]), signature="forged")
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "unauthenticated"


async def test_paid_never_moves_back_to_failed(session, fakes, api):
    await booked_session(session)
    payment = await start_payment(session)

    await post_webhook(api, webhook_body(payment["payment_id"], "SUCCESS", cf_payment_id=random.randint(10**8, 10**9)))
    late_failure = await post_webhook(api, webhook_body(payment["payment_id"], "FAILED", cf_payment_id=random.randint(10**8, 10**9)))
    assert late_failure.status_code == 200

    async with SessionLocal() as db:
        row = (await db.execute(select(Payment).where(Payment.provider_payment_id == payment["payment_id"]))).scalar_one()
    assert row.status == PaymentStatus.PAID


async def test_failed_payment_can_be_retried_with_a_new_order(session, fakes, api):
    await booked_session(session)
    first = await start_payment(session)

    await post_webhook(api, webhook_body(first["payment_id"], "FAILED", cf_payment_id=random.randint(10**8, 10**9)))
    await session.stream.wait_for("payment.updated", where=lambda p: p and p["status"] == "failed")

    retry = await start_payment(session)
    assert retry["status"] == "created"
    assert retry["payment_id"] != first["payment_id"]
    assert len(fakes.payments.created) == 2


async def test_paying_a_confirmed_booking_is_409(session, fakes, api):
    await booked_session(session)
    payment = await start_payment(session)
    start = session.stream.last_id
    await post_webhook(api, webhook_body(payment["payment_id"]))
    await session.stream.wait_for("booking.updated", after=start, where=lambda b: b["lifecycle"] == "confirmed")

    response = await session.api.post(session.url("/payments"))
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "booking_not_payable"
