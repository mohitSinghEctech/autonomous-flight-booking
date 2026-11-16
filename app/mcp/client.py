"""
One long-lived connection to the flight MCP server (a stdio subprocess).

Starting a subprocess per tool call costs seconds; one session shared by every
turn costs milliseconds, and the MCP session handles concurrent calls.

    client = FlightMCPClient()
    await client.start()      # app startup; never raises, flights may be down
    await client.search_flights(...)
    await client.stop()       # app shutdown; ends the subprocess

or, in scripts:  async with FlightMCPClient() as client: ...

Rules this follows:
  - The SDK requires the task that opens a Client to also close it, so ONE
    background task (_run) owns the connection and reopens it when it breaks.
  - The app must work without flights (bookings, profile, payments don't use
    MCP), so startup never fails and every MCP failure becomes an AppError:
    the agent shows it as a failed step and explains it; the turn goes on.
  - If the server dies, the call reconnects and is retried once. Both tools
    only read, so a retry is safe.
"""
import asyncio
import logging
import os
import sys
from contextlib import AsyncExitStack
from pathlib import Path

import anyio
from mcp import Client, StdioServerParameters
from mcp.shared.exceptions import MCPError
from mcp.types import CONNECTION_CLOSED, REQUEST_TIMEOUT

from app.core.errors import InvalidUpstreamResponse, UpstreamTimeout, UpstreamUnavailable
from app.core.settings import settings


logger = logging.getLogger(__name__)

SERVER_SCRIPT = Path(__file__).with_name("server.py")

CALL_TIMEOUT = 60        # seconds per tool call
STARTUP_WAIT = 15        # how long app startup waits for the first connection
CONNECT_TIMEOUT = 20     # one launch + handshake attempt
CONNECT_WAIT = 10        # how long a call waits for a (re)connection
RETRY_DELAYS = (1, 2, 5, 10, 30)   # background reconnect backoff, seconds

UNAVAILABLE = "Flight search is temporarily unavailable. Please try again in a moment."
TIMED_OUT = "Flight search took too long to respond. Please try again."

# A dead subprocess shows up as CONNECTION_CLOSED, or as a closed stream on write.
BROKEN_STREAM = (anyio.ClosedResourceError, anyio.BrokenResourceError, anyio.EndOfStream)


def default_server() -> StdioServerParameters:
    return StdioServerParameters(
        command=sys.executable,
        args=[str(SERVER_SCRIPT)],
        env={
            "PATH": os.environ.get("PATH", ""),
            "FLIGHT_VENDOR_TOKEN": settings.flight_vendor_token,
        },
    )


class FlightMCPClient:
    def __init__(
        self,
        server=None,
        *,
        call_timeout: float = CALL_TIMEOUT,
        startup_wait: float = STARTUP_WAIT,
        connect_wait: float = CONNECT_WAIT,
        connect_timeout: float = CONNECT_TIMEOUT,
        retry_delays: tuple[float, ...] = RETRY_DELAYS,
    ):
        # StdioServerParameters in production; tests may pass an in-process MCPServer.
        self.server = server or default_server()
        self.call_timeout = call_timeout
        self.startup_wait = startup_wait
        self.connect_wait = connect_wait
        self.connect_timeout = connect_timeout
        self.retry_delays = retry_delays

        self.connections = 0                    # successful connects, for logs and tests
        self._client: Client | None = None      # the live session, None while down
        self._task: asyncio.Task | None = None  # the owner task (_run)
        self._stopping = False
        self._wake = asyncio.Event()            # asks _run to reconnect now / to stop
        self._attempt: asyncio.Future | None = None   # result of the current/next connect attempt

    # ---- lifecycle -------------------------------------------------------

    @property
    def connected(self) -> bool:
        return self._client is not None

    async def start(self) -> None:
        """Start the owner task and wait briefly for the first connection.
        Never raises: if the server is down the app still starts, and the
        owner task keeps retrying in the background."""
        if self._task and not self._task.done():
            return

        self._stopping = False
        self._wake = asyncio.Event()
        self._attempt = asyncio.get_running_loop().create_future()
        attempt = self._attempt
        self._task = asyncio.create_task(self._run(), name="flight-mcp-client")

        try:
            await asyncio.wait_for(asyncio.shield(attempt), self.startup_wait)
        except TimeoutError:
            pass

        if not self.connected:
            logger.error("flight MCP server unavailable at startup; flight search will fail until it recovers")

    async def stop(self) -> None:
        """Close the session (which ends the subprocess) and the owner task."""
        task, self._task = self._task, None
        if task is None:
            return

        self._stopping = True
        self._wake.set()

        try:
            await asyncio.wait_for(task, timeout=10)
        except TimeoutError:
            task.cancel()
            logger.warning("flight MCP client did not stop in time; cancelled")

    async def __aenter__(self) -> "FlightMCPClient":
        await self.start()
        return self

    async def __aexit__(self, *exc) -> None:
        await self.stop()

    # ---- tools -----------------------------------------------------------

    async def search_flights(
        self,
        origin: str,
        destination: str,
        date: str,
        passengers: int,
        cabin: str,
    ) -> str:
        return await self.call_tool(
            "search_flights",
            {
                "origin": origin,
                "destination": destination,
                "date": date,
                "passengers": passengers,
                "cabin": cabin,
            },
        )

    async def get_flight_details(self, flight_id: str) -> str:
        return await self.call_tool("get_flight_details", {"flight_id": flight_id})

    async def call_tool(self, name: str, arguments: dict) -> str:
        """Call a tool on the shared session; on a dead server reconnect and retry once.
        Returns the tool's text, as before (tool-level errors are text too)."""
        for attempt in (1, 2):
            client = await self._connected_client()

            try:
                result = await client.call_tool(name, arguments, read_timeout_seconds=self.call_timeout)
            except MCPError as exc:
                if exc.error.code == REQUEST_TIMEOUT:
                    raise UpstreamTimeout(TIMED_OUT) from exc
                if exc.error.code != CONNECTION_CLOSED:
                    raise InvalidUpstreamResponse(f"Flight search failed: {exc.error.message}") from exc
                broken = exc
            except BROKEN_STREAM as exc:
                broken = exc
            else:
                return result.content[0].text

            logger.warning("flight MCP connection lost during %s (try %d): %s", name, attempt, broken)
            self._drop(client)

        raise UpstreamUnavailable(UNAVAILABLE) from broken

    # ---- connection management ---------------------------------------------

    async def _connected_client(self) -> Client:
        if self._client is not None:
            return self._client

        if self._task is None or self._stopping:
            raise UpstreamUnavailable(UNAVAILABLE)

        # Wait for the running/next attempt, and make it happen now rather than after backoff.
        attempt = self._attempt
        self._wake.set()

        try:
            await asyncio.wait_for(asyncio.shield(attempt), self.connect_wait)
        except TimeoutError:
            pass

        if self._client is None:
            raise UpstreamUnavailable(UNAVAILABLE)

        return self._client

    def _drop(self, client: Client) -> None:
        """Mark this session dead and ask _run to reconnect. Many callers may see the
        same dead session; only the first one changes anything, so there is ONE reconnect."""
        if self._client is client:
            self._client = None
            self._wake.set()

    def _finish_attempt(self) -> None:
        """Wake everyone waiting on the current attempt; later callers wait on the next one."""
        if self._attempt and not self._attempt.done():
            self._attempt.set_result(None)
        self._attempt = asyncio.get_running_loop().create_future()

    async def _run(self) -> None:
        """The owner task: opens the session, holds it until it breaks or we stop, repeats."""
        failures = 0

        try:
            while not self._stopping:
                client = None
                try:
                    async with AsyncExitStack() as stack:
                        async with asyncio.timeout(self.connect_timeout):   # a hung launch must not block us
                            client = await stack.enter_async_context(Client(self.server))

                        self._client = client
                        self.connections += 1
                        failures = 0
                        logger.info("flight MCP server connected (connection %d)", self.connections)
                        self._finish_attempt()

                        while self._client is client and not self._stopping:
                            self._wake.clear()
                            await self._wake.wait()

                except Exception as exc:   # includes the ExceptionGroup a failed launch raises
                    if client is None:
                        failures += 1
                        logger.warning("flight MCP server failed to start (attempt %d): %r", failures, exc)
                    else:
                        logger.warning("flight MCP session closed with an error: %r", exc)
                finally:
                    if client is not None and self._client is client:
                        self._client = None

                if self._stopping:
                    break

                if client is None:
                    # This attempt failed: let waiting callers fail fast, then back off,
                    # unless a caller asks for a new attempt sooner.
                    self._finish_attempt()
                    delay = self.retry_delays[min(failures, len(self.retry_delays)) - 1]
                    self._wake.clear()
                    try:
                        await asyncio.wait_for(self._wake.wait(), delay)
                    except TimeoutError:
                        pass
        finally:
            self._client = None
            if self._attempt and not self._attempt.done():
                self._attempt.set_result(None)
            logger.info("flight MCP client stopped")
