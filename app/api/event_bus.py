import asyncio

from app.api.events import SSEEvent


class SessionEventBus:

    def __init__(self):
        self._subscribers: dict[str, set[asyncio.Queue[SSEEvent]]] = {}

        # Event history per conversation.
        #
        # Example:
        # thread_id -> [event1, event2, event3]
        self._history: dict[str, list[SSEEvent]] = {}

        # Last event ID generated for each conversation.
        #
        # thread_id -> 3
        self._next_event_id: dict[str, int] = {}

    async def subscribe(
        self,
        thread_id: str,
        last_event_id: int | None = None,
    ) -> tuple[asyncio.Queue[SSEEvent], list[SSEEvent]]:

        queue: asyncio.Queue[SSEEvent] = asyncio.Queue()

        self._subscribers.setdefault(thread_id, set()).add(queue)

        history = self._history.get(thread_id, [])

        # No Last-Event-ID means this is a fresh connection.
        #
        # We don't replay old events here because the connection
        # will receive a snapshot separately.
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
    ) -> None:

        # Generate monotonically increasing IDs per conversation.
        event_id = self._next_event_id.get(thread_id, 0) + 1

        self._next_event_id[thread_id] = event_id

        event.event_id = event_id

        # Store event for reconnect/replay.
        self._history.setdefault(thread_id, []).append(event)

        subscribers = self._subscribers.get(thread_id, set())

        # Send to all currently connected clients.
        for queue in subscribers:
            await queue.put(event)

    def get_history(
        self,
        thread_id: str,
    ) -> list[SSEEvent]:

        return list(self._history.get(thread_id, []))

    def get_last_event_id(
        self,
        thread_id: str,
    ) -> int | None:

        return self._next_event_id.get(thread_id)


event_bus = SessionEventBus()