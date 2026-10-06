"""A tiny SSE client for tests: reads the stream in the background, parses events."""
import asyncio
import json

import httpx


class EventStream:

    def __init__(self, url: str, last_event_id: int | None = None):
        self.url = url
        self.headers = {"Last-Event-ID": str(last_event_id)} if last_event_id else {}
        self.events: list[dict] = []
        self.comments: list[str] = []
        self._changed = asyncio.Event()
        self._task: asyncio.Task | None = None
        self._client: httpx.AsyncClient | None = None

    async def __aenter__(self):
        self._client = httpx.AsyncClient(timeout=None)
        self._task = asyncio.create_task(self._read())
        return self

    async def __aexit__(self, *exc):
        self._task.cancel()
        try:
            await self._task
        except (asyncio.CancelledError, Exception):
            pass
        await self._client.aclose()

    @property
    def last_id(self) -> int:
        ids = [e["id"] for e in self.events if e["id"] is not None]
        return max(ids) if ids else 0

    def of(self, name: str) -> list[dict]:
        return [e for e in self.events if e["event"] == name]

    async def _read(self):
        async with self._client.stream("GET", self.url, headers=self.headers) as response:
            event = {}
            async for line in response.aiter_lines():
                if line == "":
                    if "event" in event:
                        self.events.append({
                            "id": int(event["id"]) if "id" in event else None,
                            "event": event["event"],
                            "data": json.loads(event.get("data", "null")),
                        })
                        self._changed.set()
                    event = {}
                elif line.startswith(":"):
                    self.comments.append(line)
                elif ":" in line:
                    key, _, value = line.partition(":")
                    event[key] = value.lstrip()

    async def wait_for(self, name: str, *, after: int = -1, where=None, timeout: float = 15) -> dict:
        """First event called `name` with id > after (and matching `where`)."""

        async def find():
            while True:
                for e in self.events:
                    if e["event"] == name and (e["id"] or 0) > after and (where is None or where(e["data"])):
                        return e
                self._changed.clear()
                await self._changed.wait()

        try:
            return await asyncio.wait_for(find(), timeout)
        except asyncio.TimeoutError:
            seen = [(e["id"], e["event"]) for e in self.events]
            raise AssertionError(f"no '{name}' event after id {after}. Seen: {seen}") from None
