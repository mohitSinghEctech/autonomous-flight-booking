import asyncio
import uuid

from fastapi import APIRouter, Header, HTTPException, Response
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from app.api.event_bus import event_bus
from app.api.events import SSEEvent
from app.api.runner import run_turn
from app.api.turns import turn_manager


TEST_USER_ID = "eeb6ff6a-c66f-4874-a5aa-7c773962e14e"


router = APIRouter(prefix="/api")


class MessageRequest(BaseModel):
    text: str
    client_id: str | None = None


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

    # ---------------------------------------------------------
    # Parse Last-Event-ID
    # ---------------------------------------------------------

    parsed_last_event_id: int | None = None

    if last_event_id is not None:

        try:
            parsed_last_event_id = int(last_event_id)

        except ValueError:
            raise HTTPException(
                status_code=400,
                detail="invalid_last_event_id",
            )

    # ---------------------------------------------------------
    # Subscribe before creating the snapshot.
    #
    # This is important:
    #
    #     subscribe
    #         ↓
    #     snapshot
    #         ↓
    #     live events
    #
    # Otherwise an event could arrive between snapshot creation
    # and subscription.
    # ---------------------------------------------------------

    queue, replay = await event_bus.subscribe(
        thread_id=thread_id,
        last_event_id=parsed_last_event_id,
    )

    # ---------------------------------------------------------
    # Snapshot
    # ---------------------------------------------------------

    history = event_bus.get_history(thread_id)

    snapshot_data = {
        "thread_id": thread_id,
        "last_event_id": event_bus.get_last_event_id(thread_id),
        "events": [
            {
                "id": event.event_id,
                "event": event.event,
                "data": event.data,
            }
            for event in history
        ],
    }

    snapshot_event = SSEEvent(
        event="session.snapshot",
        data=snapshot_data,
    )

    async def event_generator():

        try:

            # -------------------------------------------------
            # Fresh connection
            # -------------------------------------------------
            #
            # Send the snapshot first.
            #
            # Replaying old events is unnecessary because the
            # snapshot contains the current event history.
            #
            # -------------------------------------------------

            if parsed_last_event_id is None:

                yield snapshot_event.to_sse()

            # -------------------------------------------------
            # Reconnecting client
            # -------------------------------------------------
            #
            # Send events missed after Last-Event-ID.
            #
            # -------------------------------------------------

            else:

                for event in replay:
                    yield event.to_sse()

            # -------------------------------------------------
            # Live stream
            # -------------------------------------------------

            while True:

                try:

                    event = await asyncio.wait_for(
                        queue.get(),
                        timeout=15,
                    )

                    yield event.to_sse()

                except asyncio.TimeoutError:

                    # SSE comment.
                    #
                    # Browser ignores this but keeps the
                    # connection alive.
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

    # ---------------------------------------------------------
    # Prevent concurrent turns.
    # ---------------------------------------------------------

    if not turn_manager.acquire(thread_id):

        raise HTTPException(
            status_code=409,
            detail="turn_in_progress",
        )

    async def execute():

        try:

            await run_turn(
                thread_id=thread_id,
                user_id=TEST_USER_ID,
                message=request.text,
            )

        except Exception:
            # run_turn already publishes the SSE error.
            #
            # The background task must not bring down FastAPI.
            pass

    asyncio.create_task(
        turn_manager.run(
            thread_id,
            execute,
        )
    )

    # ---------------------------------------------------------
    # 202 = request accepted for asynchronous processing.
    # ---------------------------------------------------------

    return Response(
        content='{"accepted":true}',
        media_type="application/json",
        status_code=202,
    )