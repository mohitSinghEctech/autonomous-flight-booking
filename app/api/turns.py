import asyncio


class TurnManager:

    def __init__(self):
        self._locks: dict[str, asyncio.Lock] = {}
        self._busy: set[str] = set()

    def is_busy(self, thread_id: str) -> bool:
        return thread_id in self._busy

    def acquire(self, thread_id: str) -> bool:
        """
        Reserve the conversation for a new turn.

        This happens synchronously inside the request handler,
        before create_task(), so a second request cannot sneak in.
        """

        if thread_id in self._busy:
            return False

        self._busy.add(thread_id)

        return True

    async def run(
        self,
        thread_id: str,
        operation,
    ):
        lock = self._locks.setdefault(
            thread_id,
            asyncio.Lock(),
        )

        try:
            async with lock:
                return await operation()

        finally:
            self._busy.discard(thread_id)


turn_manager = TurnManager()