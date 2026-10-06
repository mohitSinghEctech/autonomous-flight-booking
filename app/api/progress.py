"""
How every layer reports progress to the browser, without knowing about HTTP.

The runner opens a TURN (a ContextVar). Everything running inside it — LangGraph
nodes, tools, services called from tools — calls these helpers, and the events
land on the right thread with the right turn_id. asyncio copies context into
the tasks LangGraph creates, so nodes see the turn without passing it around.

All payloads go through the contract models in events.py first.
"""
import time
import uuid
from contextvars import ContextVar
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from app.api import events as contract
from app.api.event_bus import event_bus
from app.api.events import SSEEvent


@dataclass
class TurnContext:
    thread_id: str
    turn_id: str
    origin: str = "user"                 # user | selection | approval | payment | cancel
    llm_calls: int = 0
    open_steps: set[str] = field(default_factory=set)
    started: float = field(default_factory=time.monotonic)
    input_tokens: int = 0
    output_tokens: int = 0


_turn: ContextVar[TurnContext | None] = ContextVar("turn", default=None)


def current_turn() -> TurnContext | None:
    return _turn.get()


def enter_turn(context: TurnContext):
    return _turn.set(context)


def leave_turn(token) -> None:
    _turn.reset(token)


def now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _thread(thread_id: str | None) -> str | None:
    if thread_id:
        return thread_id
    turn = current_turn()
    return turn.thread_id if turn else None


async def publish(event: str, data: Any, thread_id: str | None = None) -> None:
    target = _thread(thread_id)
    if target is None:
        return  # running outside the API (e.g. python -m app.graph): nobody is listening
    await event_bus.publish(target, SSEEvent(event=event, data=data))


async def publish_model(event: str, model: type[contract.BaseModel], data: dict, thread_id: str | None = None) -> None:
    """Validate against the contract, then publish (exclude None so partial updates stay partial)."""
    payload = model.model_validate(data).model_dump(mode="json", exclude_none=(model is contract.StepEvent))
    await publish(event, payload, thread_id)


# ---- status ---------------------------------------------------------------------

async def set_status(busy: bool, stage: str, text: str, thread_id: str | None = None) -> None:
    await publish_model("status", contract.StatusEvent, {"busy": busy, "stage": stage, "text": text}, thread_id)


# ---- steps (the agent trace in the chat) -------------------------------------------

async def start_step(
    kind: str,
    title: str,
    *,
    tool: str | None = None,
    detail: str | None = None,
    stage: str | None = None,
    status_text: str | None = None,
    status: str = "running",
) -> str:
    turn = current_turn()
    step_id = f"s{uuid.uuid4().hex[:8]}"

    if stage:
        await set_status(True, stage, status_text or f"{title}…")

    await publish_model("step", contract.StepEvent, {
        "id": step_id,
        "turn_id": turn.turn_id if turn else None,
        "kind": kind,
        "tool": tool,
        "title": title,
        "detail": detail,
        "status": status,
        "started_at": now(),
    })

    if turn and status == "running":
        turn.open_steps.add(step_id)

    return step_id


async def finish_step(step_id: str, *, status: str = "done", detail: str | None = None, thread_id: str | None = None) -> None:
    turn = current_turn()
    if turn:
        turn.open_steps.discard(step_id)

    await publish_model("step", contract.StepEvent, {
        "id": step_id,
        "status": status,
        "detail": detail,
        "ended_at": now(),
    }, thread_id)


# ---- messages, errors -----------------------------------------------------------------

async def publish_message(role: str, text: str, *, message_id: str | None = None, thread_id: str | None = None) -> None:
    await publish_model("message", contract.MessageEvent, {
        "id": message_id or f"m{uuid.uuid4().hex[:10]}",
        "role": role,
        "text": text,
        "created_at": now(),
    }, thread_id)


async def publish_error(code: str, message: str, *, recoverable: bool = True, thread_id: str | None = None) -> None:
    await publish_model("error", contract.ErrorEvent, {
        "code": code,
        "message": message,
        "recoverable": recoverable,
    }, thread_id)
