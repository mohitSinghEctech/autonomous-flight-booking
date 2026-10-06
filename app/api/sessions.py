"""
Per-conversation memory of the API layer.

Each session keeps a PROJECTION: every published event is applied to a dict,
exactly the way the browser's reducer does it. That dict IS the session.snapshot
a reconnecting browser receives, and it answers questions like
"is an approval pending, and which one?" without asking LangGraph.

Sessions live in memory while the process runs and are saved to Postgres
(chat_sessions) at the end of every turn, so a restart or redeploy keeps every
conversation. The agent's memory is saved separately by LangGraph's checkpointer.

Still single-process: the turn lock and the live event fan-out are in memory,
so run ONE API instance (see docs/api-layer.md §8).
"""
import asyncio
import logging
import uuid
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert

from app.db.models import ChatSession
from app.db.session import SessionLocal

logger = logging.getLogger(__name__)


def empty_state() -> dict[str, Any]:
    return {
        "status": {"busy": False, "stage": "idle", "text": "Standing by"},
        "turns": [],
        "steps": [],
        "messages": [],
        "timeline": [],
        "search": None,
        "flights": [],
        "selection": None,
        "approval": None,
        "passenger_request": None,
        "booking": None,
        "payment": None,
    }


@dataclass
class Session:
    thread_id: str
    user_id: str
    state: dict[str, Any] = field(default_factory=empty_state)

    # client_id -> turn_id: a retried POST /messages returns the same turn
    seen_client_ids: dict[str, str] = field(default_factory=dict)

    # approval_id / request_id -> decision: a double click gets the same answer
    resolved: dict[str, str] = field(default_factory=dict)

    # "graph" = a LangGraph interrupt (book/change/passengers), "cancel" = app-level
    pending_kind: str | None = None

    # the "Waiting for your approval" step, finished when the user answers
    waiting_step_id: str | None = None

    turn_counter: int = 0

    def next_turn_id(self) -> str:
        self.turn_counter += 1
        return f"t{self.turn_counter}"

    def meta(self, last_event_id: int) -> dict[str, Any]:
        return {
            "seen_client_ids": self.seen_client_ids,
            "resolved": self.resolved,
            "pending_kind": self.pending_kind,
            "waiting_step_id": self.waiting_step_id,
            "turn_counter": self.turn_counter,
            "last_event_id": last_event_id,
        }


class SessionStore:

    def __init__(self):
        self._sessions: dict[str, Session] = {}

        # Cashfree order id -> thread_id, so a webhook knows whose stream to update
        self.order_threads: dict[str, str] = {}

        self._saving: set[asyncio.Task] = set()

    async def create(self, user_id: str, thread_id: str | None = None) -> Session:
        session = Session(thread_id=thread_id or str(uuid.uuid4()), user_id=user_id)
        self._sessions[session.thread_id] = session
        await self.save(session)
        return session

    def get(self, thread_id: str) -> Session | None:
        return self._sessions.get(thread_id)

    async def load(self, thread_id: str) -> Session | None:
        """Memory first; after a restart, from Postgres (and the event ids continue)."""

        session = self._sessions.get(thread_id)
        if session is not None:
            return session

        async with SessionLocal() as db:
            row = await db.get(ChatSession, thread_id)

        if row is None:
            return None

        meta = row.meta
        session = Session(
            thread_id=thread_id,
            user_id=str(row.user_id),
            state={**empty_state(), **row.state},
            seen_client_ids=meta.get("seen_client_ids", {}),
            resolved=meta.get("resolved", {}),
            pending_kind=meta.get("pending_kind"),
            waiting_step_id=meta.get("waiting_step_id"),
            turn_counter=meta.get("turn_counter", 0),
        )

        # a turn that was running when the process stopped is not running any more
        session.state["status"] = {"busy": False, "stage": "idle", "text": "Standing by"}
        if session.state["approval"] or session.state["passenger_request"]:
            session.state["status"] = {"busy": False, "stage": "awaiting_approval", "text": "Waiting for you"}

        from app.api.event_bus import event_bus      # event_bus imports this module
        event_bus.restore_counter(thread_id, meta.get("last_event_id", 0))

        self._sessions.setdefault(thread_id, session)
        return self._sessions[thread_id]

    async def thread_for_payment(self, payment_id: str) -> str | None:
        """Which conversation shows this Cashfree order (used by webhooks after a restart)."""
        async with SessionLocal() as db:
            result = await db.execute(
                select(ChatSession.thread_id)
                .where(ChatSession.state["payment"]["payment_id"].astext == payment_id)
                .order_by(ChatSession.updated_at.desc())
                .limit(1)
            )
        thread_id = result.scalar_one_or_none()
        if thread_id:
            await self.load(thread_id)        # so the projection exists for publish()
        return thread_id

    def save_soon(self, session: Session) -> None:
        """Save without making the caller wait (a turn must release its lock right away).
        Every save writes the CURRENT in-memory state, so overlapping saves still end on the latest."""
        task = asyncio.create_task(self.save(session))
        self._saving.add(task)
        task.add_done_callback(self._saving.discard)

    async def flush(self) -> None:
        """Wait for pending saves (shutdown, tests)."""
        loop = asyncio.get_running_loop()
        pending = [task for task in self._saving if task.get_loop() is loop]
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)

    async def save(self, session: Session) -> None:
        """Upsert the whole session. Never raises: losing a save must not fail a turn."""

        from app.api.event_bus import event_bus
        meta = session.meta(event_bus.get_last_event_id(session.thread_id))

        try:
            async with SessionLocal() as db:
                statement = insert(ChatSession).values(
                    thread_id=session.thread_id,
                    user_id=uuid.UUID(session.user_id),
                    state=session.state,
                    meta=meta,
                )
                await db.execute(statement.on_conflict_do_update(
                    index_elements=[ChatSession.thread_id],
                    set_={"state": statement.excluded.state, "meta": statement.excluded.meta,
                          "updated_at": statement.excluded.updated_at},
                ))
                await db.commit()
        except Exception:
            logger.exception("could not save session %s", session.thread_id)

    def apply(self, thread_id: str, event: str, data: Any) -> None:
        session = self._sessions.get(thread_id)
        if session is not None:
            apply_event(session.state, event, data)


# ---- the projection (mirrors the UI reducer) ------------------------------------

def apply_event(state: dict[str, Any], event: str, data: Any) -> None:

    if event == "status":
        state["status"] = data

    elif event == "turn.started":
        _upsert(state["turns"], data, "turn_id")
        _add_once(state["timeline"], {"type": "turn", "id": data["turn_id"]})

    elif event == "step":
        _upsert(state["steps"], data, "id")

    elif event == "message":
        _upsert(state["messages"], data, "id")
        _add_once(state["timeline"], {"type": "msg", "id": data["id"]})

    elif event == "flights.results":
        state["search"] = data["query"]
        state["flights"] = data["flights"]
        state["selection"] = None

    elif event == "flights.selected":
        state["selection"] = data

    elif event == "approval.required":
        state["approval"] = data

    elif event == "approval.resolved":
        if (state["approval"] or {}).get("approval_id") == data["approval_id"]:
            state["approval"] = None

    elif event == "passenger.required":
        state["passenger_request"] = data

    elif event == "passenger.resolved":
        if (state["passenger_request"] or {}).get("request_id") == data["request_id"]:
            state["passenger_request"] = None

    elif event == "booking.updated":
        state["booking"] = data

    elif event == "payment.updated":
        state["payment"] = data

    elif event == "error":
        error_id = f"error-{len(state['messages'])}"
        state["messages"].append({"id": error_id, "role": "system", "text": data["message"]})
        state["timeline"].append({"type": "msg", "id": error_id})


def _upsert(items: list[dict], item: dict, key: str) -> None:
    for index, existing in enumerate(items):
        if existing.get(key) == item.get(key):
            items[index] = {**existing, **item}
            return
    items.append(dict(item))


def _add_once(timeline: list[dict], item: dict) -> None:
    if item not in timeline:
        timeline.append(item)


session_store = SessionStore()
