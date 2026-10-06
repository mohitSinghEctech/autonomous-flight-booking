class TurnManager:
    """
    One unit of work per conversation at a time.

    acquire() runs synchronously inside the request handler, BEFORE the background
    task exists — so a second request can never slip in between "accepted" and
    "started" (that race is why it is not done inside the task).

    Waiting for the user (approval, passenger details) is NOT busy: the contract
    lets a new message supersede the pending question.
    """

    def __init__(self):
        self._busy: set[str] = set()

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


turn_manager = TurnManager()
