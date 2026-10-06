class TurnManager:

    def __init__(self):
        self._busy: set[str] = set()
        self._waiting_for_approval: set[str] = set()

    def is_busy(
        self,
        thread_id: str,
    ) -> bool:

        return thread_id in self._busy

    def acquire(
        self,
        thread_id: str,
    ) -> bool:

        if thread_id in self._busy:
            return False

        self._busy.add(thread_id)

        return True

    def release(
        self,
        thread_id: str,
    ) -> None:

        self._busy.discard(thread_id)
        self._waiting_for_approval.discard(thread_id)

    def set_waiting_for_approval(
        self,
        thread_id: str,
    ) -> None:

        self._waiting_for_approval.add(thread_id)

    def is_waiting_for_approval(
        self,
        thread_id: str,
    ) -> bool:

        return thread_id in self._waiting_for_approval


turn_manager = TurnManager()