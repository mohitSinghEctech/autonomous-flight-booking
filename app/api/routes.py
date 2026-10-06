import asyncio
import logging
import uuid
from typing import Literal

from fastapi import APIRouter, Header, HTTPException, Response
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from app.api.event_bus import event_bus
from app.api.events import SSEEvent
from app.api.progress import publish_error
from app.api.runner import resume_turn, run_turn
from app.api.turns import turn_manager


TEST_USER_ID = "eeb6ff6a-c66f-4874-a5aa-7c773962e14e"

logger = logging.getLogger(__name__)

# asyncio keeps only a WEAK reference to tasks: without this set a running
# turn can be garbage-collected halfway through.
_background_tasks: set[asyncio.Task] = set()


def start_background(coro) -> None:
    task = asyncio.create_task(coro)
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)


router = APIRouter(prefix="/api")


class MessageRequest(BaseModel):
    text: str
    client_id: str | None = None


class ApprovalRequest(BaseModel):
    # contract §3.4: the UI sends {"decision": "approved" | "rejected"}
    decision: Literal["approved", "rejected"]


@router.post("/sessions")
async def create_session():

    thread_id = str(uuid.uuid4())

    return {
        "thread_id": thread_id,
        "contract_version": "1.0",
    }


@router.get("/sessions/{thread_id}/stream")
async def stream_session(
    thread_id: str,
    last_event_id: str | None = Header(default=None),
):

    parsed_last_event_id = None

    if last_event_id is not None:

        try:
            parsed_last_event_id = int(last_event_id)

        except ValueError:

            raise HTTPException(
                status_code=400,
                detail="invalid_last_event_id",
            )

    queue, replay = await event_bus.subscribe(
        thread_id=thread_id,
        last_event_id=parsed_last_event_id,
    )

    history = event_bus.get_history(thread_id)

    snapshot = SSEEvent(
        event="session.snapshot",
        data={
            "thread_id": thread_id,
            "last_event_id": event_bus.get_last_event_id(
                thread_id
            ),
            "events": [
                {
                    "id": event.event_id,
                    "event": event.event,
                    "data": event.data,
                }
                for event in history
            ],
        },
    )

    async def event_generator():

        try:

            if parsed_last_event_id is None:

                yield snapshot.to_sse()

            else:

                for event in replay:
                    yield event.to_sse()

            while True:

                try:

                    event = await asyncio.wait_for(
                        queue.get(),
                        timeout=15,
                    )

                    yield event.to_sse()

                except asyncio.TimeoutError:

                    yield ": heartbeat\n\n"

        except asyncio.CancelledError:

            raise

        finally:

            await event_bus.unsubscribe(
                thread_id,
                queue,
            )

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


@router.post("/sessions/{thread_id}/messages")
async def send_message(
    thread_id: str,
    request: MessageRequest,
):

    if not turn_manager.acquire(thread_id):

        raise HTTPException(
            status_code=409,
            detail="turn_in_progress",
        )

    async def execute():

        try:

            result = await run_turn(
                thread_id=thread_id,
                user_id=TEST_USER_ID,
                message=request.text,
            )

            if result.get("waiting_for_approval"):
                turn_manager.set_waiting_for_approval(
                    thread_id
                )

        except Exception:

            # run_turn already published an error event for the UI;
            # this makes it visible in the server log as well.
            logger.exception("turn failed (thread %s)", thread_id)

        finally:

            if not turn_manager.is_waiting_for_approval(
                thread_id
            ):
                turn_manager.release(thread_id)

    try:

        # execute() -> a coroutine; create_task needs the coroutine,
        # not the function.
        start_background(execute())

    except Exception:

        # Nothing started, so nothing will ever release the lock: do it here.
        turn_manager.release(thread_id)
        raise

    return Response(
        content='{"accepted":true}',
        media_type="application/json",
        status_code=202,
    )


@router.post(
    "/sessions/{thread_id}/approvals/{approval_id}"
)
async def resolve_approval(
    thread_id: str,
    approval_id: str,
    request: ApprovalRequest,
):

    if not turn_manager.is_busy(thread_id):

        raise HTTPException(
            status_code=409,
            detail="no_pending_approval",
        )

    async def execute():

        try:

            await resume_turn(
                thread_id=thread_id,
                approval=request.decision == "approved",
            )

        except Exception:

            logger.exception("resume failed (thread %s)", thread_id)

        finally:

            turn_manager.release(thread_id)

    start_background(execute())

    return Response(
        content='{"accepted":true}',
        media_type="application/json",
        status_code=202,
    )