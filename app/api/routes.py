"""
HTTP surface (contract §3). Every handler is thin:

    validate -> check state -> take the turn lock -> start background work -> 202

Results never come back in these responses; they arrive on the SSE stream.
Errors are always {"error": {"code", "message", "retryable"}} (see errors.py).
"""
import asyncio
import json
import logging
import os

from fastapi import APIRouter, Header, Request
from fastapi.responses import JSONResponse, StreamingResponse

from app.api import runner
from app.api.errors import ApiError
from app.api.event_bus import event_bus
from app.api.events import (
    CONTRACT_VERSION,
    ApprovalIn,
    FlightSelectionIn,
    MessageIn,
    PassengersIn,
    SSEEvent,
)
from app.api.progress import publish_message
from app.api.sessions import Session, session_store
from app.api.turns import turn_manager
from app.api.views import local_time
from app.providers import all_providers
from app.providers.payment.cashfree import parse_webhook


# Until Firebase auth is wired (contract §2), every session belongs to this user.
DEMO_USER_ID = os.getenv("DEMO_USER_ID", "eeb6ff6a-c66f-4874-a5aa-7c773962e14e")

HEARTBEAT_SECONDS = 15

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api")
webhooks = APIRouter(prefix="/api/webhooks")

# asyncio keeps only a WEAK reference to tasks: without this set a running
# turn can be garbage-collected halfway through.
_background_tasks: set[asyncio.Task] = set()


def accepted(turn_id: str | None = None) -> JSONResponse:
    return JSONResponse({"accepted": True, "turn_id": turn_id}, status_code=202)


def get_session(thread_id: str) -> Session:
    return session_store.ensure(thread_id, DEMO_USER_ID)


def start_turn(session: Session, coro) -> None:
    """Lock is already held. Run the work in the background; always release."""

    async def guarded():
        try:
            await coro
        except Exception:
            logger.exception("background work failed (thread %s)", session.thread_id)
        finally:
            turn_manager.release(session.thread_id)

    try:
        task = asyncio.create_task(guarded())
    except Exception:
        coro.close()
        turn_manager.release(session.thread_id)
        raise

    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)


def lock_or_409(session: Session) -> None:
    if not turn_manager.acquire(session.thread_id):
        raise ApiError(409, "turn_in_progress", "ATLAS is still working on your last request.", retryable=True)


# ---- health + sessions ------------------------------------------------------------------

@router.get("/health")
async def health():
    return {"status": "ok", "contract_version": CONTRACT_VERSION}


@router.post("/sessions", status_code=201)
async def create_session():
    session = session_store.create(DEMO_USER_ID)
    return {"thread_id": session.thread_id, "contract_version": CONTRACT_VERSION}


# ---- the stream ------------------------------------------------------------------------

@router.get("/sessions/{thread_id}/stream")
async def stream_session(
    thread_id: str,
    request: Request,
    last_event_id: str | None = Header(default=None),
    access_token: str | None = None,          # contract §2 (not verified until auth is wired)
):
    """
    1. subscribe first (so nothing published from now on is missed)
    2. send session.snapshot with id = last event id -> the browser redraws from it
    3. stream live events, skipping any the snapshot already contains
    """
    session = get_session(thread_id)

    queue, _ = await event_bus.subscribe(thread_id)

    snapshot_id = event_bus.get_last_event_id(thread_id)
    snapshot = SSEEvent(
        event="session.snapshot",
        data={"contract_version": CONTRACT_VERSION, "thread_id": thread_id, **session.state},
        event_id=snapshot_id or None,
    )

    async def event_generator():
        try:
            yield "retry: 3000\n\n"
            yield snapshot.to_sse()

            while True:
                if await request.is_disconnected():
                    break

                try:
                    event = await asyncio.wait_for(queue.get(), timeout=HEARTBEAT_SECONDS)
                except asyncio.TimeoutError:
                    yield ": ping\n\n"
                    continue

                if event.event_id is not None and event.event_id <= snapshot_id:
                    continue          # already inside the snapshot

                yield event.to_sse()

        finally:
            await event_bus.unsubscribe(thread_id, queue)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


# ---- chat --------------------------------------------------------------------------------

@router.post("/sessions/{thread_id}/messages", status_code=202)
async def send_message(thread_id: str, body: MessageIn):
    session = get_session(thread_id)

    # retry-safe: the same client_id is the same request
    if body.client_id in session.seen_client_ids:
        return accepted(session.seen_client_ids[body.client_id])

    lock_or_409(session)

    turn_id = f"t{session.turn_counter + 1}"
    session.seen_client_ids[body.client_id] = turn_id

    # the user's bubble appears immediately, with the id the browser made
    await publish_message("user", body.text, message_id=body.client_id, thread_id=thread_id)

    start_turn(session, runner.run_message(session, body.text, title=body.text[:80]))

    return accepted(turn_id)


# ---- the user's answers --------------------------------------------------------------------

@router.post("/sessions/{thread_id}/approvals/{approval_id}", status_code=202)
async def decide(thread_id: str, approval_id: str, body: ApprovalIn):
    session = get_session(thread_id)
    pending = session.state["approval"]

    if pending is None or pending["approval_id"] != approval_id:
        previous = session.resolved.get(approval_id)

        if previous == body.decision:
            return accepted()               # double click: same answer, nothing runs twice

        if previous is not None:
            raise ApiError(409, "approval_already_resolved", f"This was already {previous}.")

        raise ApiError(409, "approval_not_pending", "There is no such approval waiting.")

    lock_or_409(session)
    session.resolved[approval_id] = body.decision

    start_turn(session, runner.resume_approval(session, approval_id, body.decision))

    return accepted()


@router.post("/sessions/{thread_id}/passenger-requests/{request_id}", status_code=202)
async def add_passengers(thread_id: str, request_id: str, body: PassengersIn):
    session = get_session(thread_id)
    pending = session.state["passenger_request"]

    if pending is None or pending["request_id"] != request_id:
        if request_id in session.resolved:
            return accepted()
        raise ApiError(409, "approval_not_pending", "There is no such passenger request waiting.")

    if body.decision == "provided" and len(body.passengers) != pending["needed"]:
        raise ApiError(422, "validation_error", f"Please add exactly {pending['needed']} passenger(s).")

    lock_or_409(session)
    session.resolved[request_id] = body.decision

    passengers = [p.model_dump() for p in body.passengers]
    start_turn(session, runner.resume_passengers(session, request_id, body.decision, passengers))

    return accepted()


@router.post("/sessions/{thread_id}/flight-selection", status_code=202)
async def select_flight(thread_id: str, body: FlightSelectionIn):
    session = get_session(thread_id)

    flight = next((f for f in session.state["flights"] if f["flight_id"] == body.flight_id), None)
    if flight is None:
        raise ApiError(404, "flight_not_found", "That flight is not in the current results. Search again.")

    if (session.state["booking"] or {}).get("lifecycle") == "confirmed":
        raise ApiError(409, "booking_not_payable", "Your booking is already paid. Changes aren't supported.")

    lock_or_409(session)

    held = (session.state["booking"] or {}).get("lifecycle") in ("held", "awaiting_payment")
    time = local_time(flight["departure_datetime"])[11:16]
    shown = f"{'Switch to' if held else 'I’ll take'} {flight['flight_name']} at {time} ({flight['price']:.2f} {flight['currency']})."

    # the LLM gets an exact instruction; the user sees a friendly line
    instruction = (
        f"I choose flight_id {flight['flight_id']} ({flight['flight_name']}, departs {time}). "
        f"Book exactly this flight for the passengers of this trip."
    )

    turn_id = f"t{session.turn_counter + 1}"
    await publish_message("user", shown, thread_id=thread_id)
    start_turn(session, runner.run_message(session, instruction, title=shown, origin="selection"))

    return accepted(turn_id)


# ---- payments + cancellation (buttons) -----------------------------------------------------------

@router.post("/sessions/{thread_id}/payments", status_code=202)
async def start_payment(thread_id: str):
    session = get_session(thread_id)
    booking = session.state["booking"]

    if not booking or booking.get("lifecycle") in ("cancelled", "expired"):
        raise ApiError(409, "no_active_booking", "There is no booking to pay for.")

    if booking.get("lifecycle") == "confirmed":
        raise ApiError(409, "booking_not_payable", "This booking is already paid.")

    lock_or_409(session)
    start_turn(session, runner.start_payment(session))

    return accepted()


@router.post("/sessions/{thread_id}/payments/{payment_id}/sync", status_code=202)
async def sync_payment(thread_id: str, payment_id: str):
    session = get_session(thread_id)

    if (session.state["payment"] or {}).get("payment_id") != payment_id:
        raise ApiError(404, "payment_not_found", "Unknown payment.")

    # not a turn: checking a payment must never block the chat
    task = asyncio.create_task(runner.sync_payment(session))
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)

    return accepted()


@router.post("/sessions/{thread_id}/booking/cancel", status_code=202)
async def cancel_booking(thread_id: str):
    session = get_session(thread_id)

    if (session.state["booking"] or {}).get("lifecycle") not in ("held", "awaiting_payment"):
        raise ApiError(409, "no_active_booking", "There is no held booking to cancel.")

    lock_or_409(session)
    start_turn(session, runner.request_cancellation(session))

    return accepted()


# ---- Cashfree -> us ---------------------------------------------------------------------------------

@webhooks.post("/cashfree")
async def cashfree_webhook(
    request: Request,
    x_webhook_signature: str | None = Header(default=None),
    x_webhook_timestamp: str | None = Header(default=None),
):
    """
    Server to server. Verified on the RAW body, deduplicated by (provider, event id),
    applied through PaymentService.apply_provider_status — the same path /sync uses.
    Returns 200 fast, also for duplicates (Cashfree retries anything else).
    """
    raw = await request.body()

    if not all_providers.payment_provider.verify_webhook(raw, x_webhook_timestamp or "", x_webhook_signature or ""):
        raise ApiError(401, "unauthenticated", "Invalid webhook signature.")

    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ApiError(400, "validation_error", "Webhook body is not JSON.") from exc

    event = parse_webhook(payload)

    if not event["order_id"]:
        return {"ok": True, "ignored": "no order id"}

    duplicate = await runner.apply_webhook(
        event["order_id"], event["status"], event["event_id"], event["event_type"], payload,
    )

    return {"ok": True, "duplicate": duplicate}
