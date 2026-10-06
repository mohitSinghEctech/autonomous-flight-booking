"""
The runner: every unit of background work is a TURN.

    turn.started -> status busy -> (steps, messages, domain events) -> turn.completed -> status idle|awaiting

Routes start these functions as background tasks (after taking the turn lock).
Nothing here raises to the caller: failures become an `error` event, failed
steps and turn.completed{outcome: failed}.
"""
import logging
import uuid
from contextlib import asynccontextmanager

from langgraph.types import Command

from app.agent.graph import graph
from app.agent.handlers import to_booking_state, to_payment_state
from app.api import events as contract
from app.api import progress
from app.api.errors import to_error_code
from app.api.sessions import Session, session_store
from app.api.views import booking_view, flight_from_booking, payment_view
from app.core.errors import NoActiveBooking
from app.db.models import BookingStatus, PaymentStatus
from app.db.repositories.bookings import BookingRepository
from app.db.session import SessionLocal
from app.models import PaymentStatus as ProviderPaymentStatus
from app.services.booking import BookingService
from app.services.payment import PaymentService


logger = logging.getLogger(__name__)


def build_config(thread_id: str) -> dict:
    return {"configurable": {"thread_id": thread_id}}


# ---- the turn wrapper ------------------------------------------------------------

@asynccontextmanager
async def turn(session: Session, title: str, origin: str):
    context = progress.TurnContext(session.thread_id, session.next_turn_id(), origin)
    token = progress.enter_turn(context)
    outcome = "completed"

    await progress.publish_model("turn.started", contract.TurnStartedEvent, {"turn_id": context.turn_id, "title": title})
    await progress.set_status(True, "thinking", "Thinking…")

    try:
        yield context

        if is_waiting(session):
            outcome = "interrupted"

    except Exception as exc:
        outcome = "failed"
        logger.exception("turn %s failed (thread %s)", context.turn_id, session.thread_id)

        for step_id in list(context.open_steps):
            await progress.finish_step(step_id, status="failed")

        code, message = to_error_code(exc)
        await progress.publish_error(code, message)

    finally:
        await progress.publish_model("turn.completed", contract.TurnCompletedEvent, {"turn_id": context.turn_id, "outcome": outcome})

        if is_waiting(session):
            text = "Waiting for passenger details" if session.state["passenger_request"] else "Waiting for your approval"
            await progress.set_status(False, "awaiting_approval", text)
        else:
            await progress.set_status(False, "idle", "Standing by")

        progress.leave_turn(token)


def is_waiting(session: Session) -> bool:
    return bool(session.state["approval"] or session.state["passenger_request"])


# ---- graph helpers ------------------------------------------------------------------

async def agent_values(thread_id: str) -> dict:
    snapshot = await graph.aget_state(build_config(thread_id))
    return snapshot.values or {}


async def sync_agent_state(thread_id: str, values: dict, note: str | None = None) -> None:
    """Things changed outside the graph (payment button, webhook, cancel): tell the agent,
    so its next LLM call sees the real booking/payment. Skipped while the graph is paused.

    `note` is also appended to the conversation: the model trusts the history it reads
    ("your seat is on hold") more than a state flag, so the history must say what changed."""
    if note:
        values = {**values, "messages": [{"role": "assistant", "content": note}]}
    try:
        snapshot = await graph.aget_state(build_config(thread_id))
        if snapshot.values and not snapshot.next:
            await graph.aupdate_state(build_config(thread_id), values)
    except Exception:
        logger.exception("could not sync agent state (thread %s)", thread_id)


async def handle_graph_result(session: Session, result: dict, origin: str) -> None:
    """The graph stopped. If it paused at interrupt(), show the user what it needs."""

    interrupts = result.get("__interrupt__")
    if not interrupts:
        return

    value = interrupts[0].value

    if value.get("type") == "approval":
        approval = value["approval"]

        await progress.publish_model("flights.selected", contract.FlightSelectedEvent, {
            "flight_id": approval["flight_id"],
            "by": "user" if origin == "selection" else "ai",
            "reason": "Your choice" if origin == "selection" else "Best match for your request",
        })
        await progress.publish_model("approval.required", contract.ApprovalRequiredEvent, approval)

        session.pending_kind = "graph"
        session.waiting_step_id = await progress.start_step(
            "approval", "Waiting for your approval", detail=approval["message"], status="waiting",
        )

    elif value.get("type") == "passengers":
        request = value["request"]

        await progress.publish_model("passenger.required", contract.PassengerRequiredEvent, request)

        session.pending_kind = "graph"
        session.waiting_step_id = await progress.start_step(
            "approval", "Waiting for passenger details", detail=request["message"], status="waiting",
        )


async def close_waiting_step(session: Session, status: str, detail: str) -> None:
    if session.waiting_step_id:
        await progress.finish_step(session.waiting_step_id, status=status, detail=detail)
        session.waiting_step_id = None


async def supersede_pending(session: Session) -> None:
    """A new request while something waits for the user: close the old question first."""

    approval = session.state["approval"]
    request = session.state["passenger_request"]

    if approval:
        if session.pending_kind == "graph":
            await graph.ainvoke(Command(resume="superseded"), config=build_config(session.thread_id))
        session.resolved[approval["approval_id"]] = "superseded"
        await progress.publish_model("approval.resolved", contract.ApprovalResolvedEvent,
                                     {"approval_id": approval["approval_id"], "decision": "superseded"})

    if request:
        await graph.ainvoke(Command(resume={"decision": "superseded"}), config=build_config(session.thread_id))
        session.resolved[request["request_id"]] = "superseded"
        await progress.publish_model("passenger.resolved", contract.PassengerResolvedEvent,
                                     {"request_id": request["request_id"], "decision": "superseded"})

    if approval or request:
        await close_waiting_step(session, "skipped", "Replaced by your new request")
        session.pending_kind = None


# ---- turns started by routes ----------------------------------------------------------------

async def run_message(session: Session, text: str, *, title: str, origin: str = "user") -> None:
    """A chat message (or a flight picked on the board, origin='selection')."""

    async with turn(session, title, origin):
        await supersede_pending(session)

        result = await graph.ainvoke(
            {
                # Only what is NEW this turn; the checkpoint keeps the rest.
                "messages": [{"role": "user", "content": text}],
                "user_id": session.user_id,
            },
            config=build_config(session.thread_id),
        )

        await handle_graph_result(session, result, origin)


async def resume_approval(session: Session, approval_id: str, decision: str) -> None:

    async with turn(session, f"Approval · {decision}", "approval"):
        await progress.publish_model("approval.resolved", contract.ApprovalResolvedEvent,
                                     {"approval_id": approval_id, "decision": decision})
        await close_waiting_step(
            session,
            "done" if decision == "approved" else "skipped",
            "You approved" if decision == "approved" else "You declined — nothing changed",
        )

        kind, session.pending_kind = session.pending_kind, None

        if kind == "cancel":
            await finish_cancellation(session, decision)
            return

        result = await graph.ainvoke(Command(resume=decision), config=build_config(session.thread_id))
        await handle_graph_result(session, result, "approval")


async def resume_passengers(session: Session, request_id: str, decision: str, passengers: list[dict]) -> None:

    async with turn(session, "Passenger details", "passengers"):
        saved = []

        if decision == "provided":
            step_id = await progress.start_step(
                "db", "Saving passenger details", stage="loading_passengers", status_text="Saving passenger details…",
            )
            async with SessionLocal() as db_session:
                created = await BookingService(db_session).add_passengers(uuid.UUID(session.user_id), passengers)
            saved = [{"id": str(p.id), "name": f"{p.given_name} {p.family_name}"} for p in created]
            await progress.finish_step(step_id, detail=f"{len(saved)} passenger(s) saved")

        await progress.publish_model("passenger.resolved", contract.PassengerResolvedEvent,
                                     {"request_id": request_id, "decision": decision, "passengers": saved})
        await close_waiting_step(session, "done" if saved else "skipped",
                                 "Details added" if saved else "No passengers added")
        session.pending_kind = None

        result = await graph.ainvoke(
            Command(resume={"decision": decision, "passengers": saved}),
            config=build_config(session.thread_id),
        )
        await handle_graph_result(session, result, "passengers")


# ---- payments (buttons, not chat) -------------------------------------------------------------

async def start_payment(session: Session) -> None:

    async with turn(session, "Payment", "payment"):
        values = await agent_values(session.thread_id)
        if not values.get("db_booking_id"):
            raise NoActiveBooking("There is no booking to pay for.")

        step_id = await progress.start_step(
            "tool", "Creating your payment", tool="create_payment",
            stage="payment", status_text="Opening secure checkout…",
        )

        async with SessionLocal() as db_session:
            payment, booking = await PaymentService(db_session).create_payment(
                uuid.UUID(session.user_id), uuid.UUID(values["db_booking_id"]),
            )
            passengers = await BookingService(db_session).booking_passengers(booking)

        session_store.order_threads[payment.provider_payment_id] = session.thread_id

        await progress.publish("payment.updated", payment_view(payment))
        await progress.publish("booking.updated", booking_view(booking, passengers))
        await progress.finish_step(step_id, detail="Checkout ready")

        await sync_agent_state(session.thread_id, {"payment": to_payment_state(payment), "booking": to_booking_state(booking)})


async def sync_payment(session: Session) -> None:
    """Fallback when no webhook arrives: ask Cashfree directly. No turn: it must not block the chat."""

    thread_id = session.thread_id

    try:
        values = await agent_values(thread_id)

        async with SessionLocal() as db_session:
            payment, booking, changed = await PaymentService(db_session).sync_payment(
                uuid.UUID(session.user_id), uuid.UUID(values["db_booking_id"]),
            )
            passengers = await BookingService(db_session).booking_passengers(booking)

        await publish_payment_change(thread_id, payment, booking, passengers, changed)

    except Exception as exc:
        logger.exception("payment sync failed (thread %s)", thread_id)
        code, message = to_error_code(exc)
        await progress.publish_error(code, message, thread_id=thread_id)


async def apply_webhook(order_id: str, status: ProviderPaymentStatus, event_id: str, event_type: str, raw: dict) -> bool:
    """Returns True when this event was a duplicate (already processed)."""

    async with SessionLocal() as db_session:
        payment, booking, changed, duplicate = await PaymentService(db_session).apply_provider_status(
            order_id, status, event_id=event_id, event_type=event_type, raw_payload=raw,
        )
        passengers = await BookingService(db_session).booking_passengers(booking)

    thread_id = session_store.order_threads.get(order_id)

    if thread_id and not duplicate:
        await publish_payment_change(thread_id, payment, booking, passengers, changed)

    return duplicate


async def publish_payment_change(thread_id, payment, booking, passengers, changed: bool) -> None:
    await progress.publish("payment.updated", payment_view(payment), thread_id)
    await progress.publish("booking.updated", booking_view(booking, passengers), thread_id)

    if changed and payment.status == PaymentStatus.PAID:
        await progress.publish_message(
            "assistant",
            f"Payment received — booking {booking.booking_reference} is confirmed. Have a good flight!",
            thread_id=thread_id,
        )
    elif changed and payment.status == PaymentStatus.FAILED:
        await progress.publish_message(
            "assistant", "That payment didn't go through. Your seat is still held — you can try again.",
            thread_id=thread_id,
        )

    if changed:
        note = {
            PaymentStatus.PAID: f"[app] Payment received. Booking {booking.booking_reference} is now CONFIRMED.",
            PaymentStatus.FAILED: "[app] The payment failed. The booking is still held and can be paid again.",
        }.get(payment.status)
        await sync_agent_state(thread_id, {"payment": to_payment_state(payment), "booking": to_booking_state(booking)}, note)


# ---- cancellation (app-level approval, no LLM) -----------------------------------------------------

async def request_cancellation(session: Session) -> None:

    async with turn(session, "Cancel booking", "cancel"):
        values = await agent_values(session.thread_id)
        if not values.get("db_booking_id"):
            raise NoActiveBooking("There is no booking to cancel.")

        async with SessionLocal() as db_session:
            booking = await BookingRepository(db_session).get_booking(uuid.UUID(values["db_booking_id"]))
            if booking is None or booking.status not in (BookingStatus.HELD, BookingStatus.AWAITING_PAYMENT):
                raise NoActiveBooking("Only a held booking can be cancelled.")
            passengers = await BookingService(db_session).booking_passengers(booking)

        flight = next(
            (f for f in session.state["flights"] if f["flight_id"] == booking.flight_number),
            flight_from_booking(booking),
        )

        approval = {
            "approval_id": f"ap_cancel_{uuid.uuid4().hex[:10]}",
            "kind": "cancel",
            "flight_id": flight["flight_id"],
            "flight": flight,
            "passengers": [{"id": str(p.id), "name": f"{p.given_name} {p.family_name}"} for p in passengers],
            "total_amount": float(booking.total_amount),
            "currency": booking.currency,
            "message": f"Cancel booking {booking.booking_reference}? The seat will be released.",
        }

        await progress.publish_model("approval.required", contract.ApprovalRequiredEvent, approval)
        session.pending_kind = "cancel"
        session.waiting_step_id = await progress.start_step(
            "approval", "Waiting for your approval", detail=approval["message"], status="waiting",
        )


async def finish_cancellation(session: Session, decision: str) -> None:

    if decision != "approved":
        await progress.publish_message("assistant", "Okay — your booking stays as it is.")
        return

    values = await agent_values(session.thread_id)

    step_id = await progress.start_step(
        "provider", "Cancelling your booking", tool="cancel_order",
        stage="booking", status_text="Releasing your seat with the airline…",
    )

    async with SessionLocal() as db_session:
        service = BookingService(db_session)
        booking = await service.cancel_booking(uuid.UUID(session.user_id), uuid.UUID(values["db_booking_id"]))
        passengers = await service.booking_passengers(booking)

    await progress.publish("booking.updated", booking_view(booking, passengers))
    await progress.publish("payment.updated", None)
    await progress.finish_step(step_id, detail="Hold released")
    await progress.publish_message("assistant", f"Booking {booking.booking_reference} is cancelled. Nothing was charged.")

    await sync_agent_state(
        session.thread_id,
        {"booking": to_booking_state(booking), "db_booking_id": None, "payment": None},
        note=f"[app] Booking {booking.booking_reference} was CANCELLED by the user. There is no active booking now; "
             "a new flight can be searched and booked.",
    )
