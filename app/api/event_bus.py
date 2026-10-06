import asyncio

from app.api.events import SSEEvent
from app.api.sessions import session_store


HISTORY_LIMIT = 500


class SessionEventBus:
    """
    Per-conversation pub/sub.

        publish(): give the event the next id, keep it in history,
                   update the session projection, fan out to open streams.
        subscribe(): one queue per open browser tab.

    Event ids increase per thread and are never reused, so a browser can
    say "I have up to 41" (Last-Event-ID) and ignore duplicates.
    """

    def __init__(self):
        self._subscribers: dict[str, set[asyncio.Queue[SSEEvent]]] = {}
        self._history: dict[str, list[SSEEvent]] = {}
        self._next_event_id: dict[str, int] = {}

    async def subscribe(
        self,
        thread_id: str,
        last_event_id: int | None = None,
    ) -> tuple[asyncio.Queue[SSEEvent], list[SSEEvent]]:

        queue: asyncio.Queue[SSEEvent] = asyncio.Queue()

        self._subscribers.setdefault(thread_id, set()).add(queue)

        history = self._history.get(thread_id, [])

        if last_event_id is None:
            replay = []
        else:
            replay = [
                event
                for event in history
                if event.event_id is not None
                and event.event_id > last_event_id
            ]

        return queue, replay

    async def unsubscribe(
        self,
        thread_id: str,
        queue: asyncio.Queue[SSEEvent],
    ) -> None:

        subscribers = self._subscribers.get(thread_id)

        if subscribers is None:
            return

        subscribers.discard(queue)

        if not subscribers:
            self._subscribers.pop(thread_id, None)

    async def publish(
        self,
        thread_id: str,
        event: SSEEvent,
    ) -> SSEEvent:

        event_id = self._next_event_id.get(thread_id, 0) + 1
        self._next_event_id[thread_id] = event_id
        event.event_id = event_id

        history = self._history.setdefault(thread_id, [])
        history.append(event)
        del history[:-HISTORY_LIMIT]

        # keep the snapshot projection in step with what browsers receive
        session_store.apply(thread_id, event.event, event.data)

        for queue in self._subscribers.get(thread_id, set()):
            queue.put_nowait(event)

        return event

    def get_history(
        self,
        thread_id: str,
    ) -> list[SSEEvent]:

        return list(self._history.get(thread_id, []))

    def restore_counter(self, thread_id: str, last_event_id: int) -> None:
        """After a restart: continue numbering where the saved session stopped,
        so browsers (which skip ids they've seen) never miss a new event."""
        if last_event_id > self._next_event_id.get(thread_id, 0):
            self._next_event_id[thread_id] = last_event_id

    def get_last_event_id(
        self,
        thread_id: str,
    ) -> int:

        return self._next_event_id.get(thread_id, 0)


event_bus = SessionEventBus()
