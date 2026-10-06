"""
Per-conversation memory of the API layer (in-process, like InMemorySaver).

Each session keeps a PROJECTION: every published event is applied to a dict,
exactly the way the browser's reducer does it. That dict IS the session.snapshot
a reconnecting browser receives, and it answers questions like
"is an approval pending, and which one?" without asking LangGraph.

Production note: this, the event bus and the turn manager are single-process.
Several API instances need them in shared storage (Redis / Postgres).
"""
import uuid
from dataclasses import dataclass, field
from typing import Any


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


class SessionStore:

    def __init__(self):
        self._sessions: dict[str, Session] = {}

        # Cashfree order id -> thread_id, so a webhook knows whose stream to update
        self.order_threads: dict[str, str] = {}

    def create(self, user_id: str) -> Session:
        session = Session(thread_id=str(uuid.uuid4()), user_id=user_id)
        self._sessions[session.thread_id] = session
        return session

    def ensure(self, thread_id: str, user_id: str) -> Session:
        """A browser may come back with a thread_id from before a restart: recreate it."""
        if thread_id not in self._sessions:
            self._sessions[thread_id] = Session(thread_id=thread_id, user_id=user_id)
        return self._sessions[thread_id]

    def get(self, thread_id: str) -> Session | None:
        return self._sessions.get(thread_id)

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
