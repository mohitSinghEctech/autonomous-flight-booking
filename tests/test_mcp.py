"""
The MCP layer: the flight MCP server, and the one long-lived FlightMCPClient the app shares.

  - server tools: an in-process MCP client against the real server, fake Duffel behind it
  - client lifecycle: a real stdio subprocess (tests/mcp_stub_server.py) that we can kill
  - app: the lifespan starts/stops the client, and MCP being down only breaks flight search
"""
import asyncio
import json
import os
import signal
import sys
import time
from datetime import date, timedelta
from pathlib import Path

import pytest
from mcp import Client, StdioServerParameters

from app.agent import handlers
from app.core.errors import UpstreamTimeout, UpstreamUnavailable
from app.main import app as fastapi_app, lifespan
from app.mcp import server
from app.mcp.client import UNAVAILABLE, FlightMCPClient, default_server
from app.models import Flight
from tests.fakes import FakeFlightProvider

STUB_SERVER = Path(__file__).with_name("mcp_stub_server.py")


@pytest.fixture
def flights(monkeypatch) -> FakeFlightProvider:
    fake = FakeFlightProvider()
    monkeypatch.setattr(server, "flight_provider", fake)
    return fake


async def call_tool(name: str, arguments: dict):
    # Opened per call, not in a yield fixture: pytest-asyncio tears fixtures down in
    # another task, and the MCP client's anyio cancel scope must exit where it entered.
    async with Client(server.mcp) as client:
        return await client.call_tool(name, arguments)


# ---- server tools -------------------------------------------------------------


async def test_server_lists_both_flight_tools(flights):
    async with Client(server.mcp) as client:
        tools = {tool.name: tool for tool in (await client.list_tools()).tools}

    assert set(tools) == {"search_flights", "get_flight_details"}
    assert tools["get_flight_details"].input_schema["required"] == ["flight_id"]


async def test_get_flight_details_returns_the_flight(flights):
    result = await call_tool("get_flight_details", {"flight_id": "off_test_1"})

    assert not result.is_error
    assert Flight.model_validate_json(result.content[0].text) == flights.offers["off_test_1"]


async def test_get_flight_details_reports_an_unknown_flight(flights):
    result = await call_tool("get_flight_details", {"flight_id": "off_missing"})

    assert result.is_error
    assert "Flight off_missing not found." in result.content[0].text


async def test_get_flight_details_requires_a_flight_id(flights):
    result = await call_tool("get_flight_details", {})

    assert result.is_error
    assert "flight_id" in result.content[0].text


async def test_search_flights_returns_every_offer(flights):
    day = (date.today() + timedelta(days=30)).isoformat()

    result = await call_tool(
        "search_flights",
        {"origin": "DEL", "destination": "DXB", "date": day, "passengers": 1, "cabin": "economy"},
    )

    assert not result.is_error
    found = [Flight.model_validate(flight) for flight in json.loads(result.content[0].text)]
    assert found == list(flights.offers.values())


async def test_client_get_flight_details_goes_through_the_server(flights):
    async with FlightMCPClient(server.mcp) as client:
        raw = await client.get_flight_details("off_test_2")

    assert Flight.model_validate_json(raw) == flights.offers["off_test_2"]


# ---- client lifecycle (real subprocess) ------------------------------------------


def stub_server(fail_flag: Path | None = None) -> StdioServerParameters:
    env = {"PATH": os.environ.get("PATH", "")}
    if fail_flag:
        env["MCP_STUB_FAIL_FLAG"] = str(fail_flag)
    return StdioServerParameters(command=sys.executable, args=[str(STUB_SERVER)], env=env)


def stub_client(fail_flag: Path | None = None, **options) -> FlightMCPClient:
    options = {"connect_wait": 15, **options}
    return FlightMCPClient(stub_server(fail_flag), **options)


async def server_pid(client: FlightMCPClient) -> int:
    return int(await client.call_tool("pid", {}))


def is_running(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False


async def wait_until(condition, timeout: float = 10) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if condition():
            return True
        await asyncio.sleep(0.05)
    return condition()


@pytest.fixture
def fail_flag(tmp_path) -> Path:
    """While this file exists, the stub server crashes on launch."""
    flag = tmp_path / "mcp-down"
    flag.touch()
    return flag


async def test_one_subprocess_serves_every_call_and_stops_with_the_client():
    client = stub_client()
    await client.start()
    try:
        pid = await server_pid(client)
        assert is_running(pid)

        details = Flight.model_validate_json(await client.get_flight_details("off_test_1"))
        day = (date.today() + timedelta(days=30)).isoformat()
        found = json.loads(await client.search_flights("DEL", "DXB", day, 1, "economy"))

        assert details.flight_id == "off_test_1"
        assert len(found) == 3
        assert await server_pid(client) == pid
        assert client.connections == 1
    finally:
        await client.stop()

    assert await wait_until(lambda: not is_running(pid)), "MCP subprocess left running after stop()"


async def test_concurrent_calls_share_the_process_and_a_slow_one_blocks_nobody():
    async with stub_client() as client:
        slow = asyncio.create_task(client.get_flight_details("off_slow"))   # takes 30 s

        started = time.monotonic()
        results = await asyncio.gather(*[client.get_flight_details(f"off_test_{i % 3}") for i in range(10)])
        elapsed = time.monotonic() - started

        assert [Flight.model_validate_json(r).flight_id for r in results] == [f"off_test_{i % 3}" for i in range(10)]
        assert elapsed < 5
        assert not slow.done()
        assert client.connections == 1

        slow.cancel()
        with pytest.raises(asyncio.CancelledError):
            await slow

        # a cancelled caller leaves the shared session usable
        assert Flight.model_validate_json(await client.get_flight_details("off_test_0")).flight_id == "off_test_0"


async def test_a_dead_server_is_replaced_transparently():
    async with stub_client() as client:
        first = await server_pid(client)
        os.kill(first, signal.SIGKILL)

        raw = await client.get_flight_details("off_test_1")   # no error reaches the caller

        assert Flight.model_validate_json(raw).flight_id == "off_test_1"
        second = await server_pid(client)
        assert second != first
        assert client.connections == 2


async def test_many_calls_hitting_a_dead_server_share_one_reconnect():
    async with stub_client() as client:
        os.kill(await server_pid(client), signal.SIGKILL)

        results = await asyncio.gather(*[client.get_flight_details("off_test_2") for _ in range(8)])

        assert all(Flight.model_validate_json(r).flight_id == "off_test_2" for r in results)
        assert client.connections == 2


async def test_a_late_failure_on_the_old_session_does_not_drop_the_new_one():
    # A call still running on the dead session can fail AFTER another caller reconnected.
    # Reproduced deterministically by reporting the old session dead once more.
    async with stub_client() as client:
        old_session = client._client
        os.kill(await server_pid(client), signal.SIGKILL)
        await client.get_flight_details("off_test_0")          # reconnects
        new_pid = await server_pid(client)

        client._drop(old_session)

        assert client.connected
        assert await server_pid(client) == new_pid
        assert client.connections == 2


async def test_a_slow_call_times_out_and_the_session_survives():
    async with stub_client(call_timeout=0.5) as client:
        with pytest.raises(UpstreamTimeout):
            await client.get_flight_details("off_slow")

        assert Flight.model_validate_json(await client.get_flight_details("off_test_0")).flight_id == "off_test_0"
        assert client.connections == 1


async def test_start_does_not_fail_when_the_server_cannot_launch(fail_flag):
    client = stub_client(fail_flag, connect_wait=5)

    started = time.monotonic()
    await client.start()           # must not raise: the app starts without flights
    try:
        assert time.monotonic() - started < 10
        assert not client.connected

        with pytest.raises(UpstreamUnavailable, match="temporarily unavailable"):
            await client.get_flight_details("off_test_0")
    finally:
        await client.stop()


async def test_a_call_brings_the_server_back_as_soon_as_it_can_start(fail_flag):
    # Backoff is 60 s, so only the caller's own reconnect request can explain a quick recovery.
    async with stub_client(fail_flag, retry_delays=(60,)) as client:
        assert not client.connected
        fail_flag.unlink()

        raw = await client.get_flight_details("off_test_1")

        assert Flight.model_validate_json(raw).flight_id == "off_test_1"
        assert client.connected


async def test_the_client_reconnects_in_the_background_without_any_call(fail_flag):
    async with stub_client(fail_flag, retry_delays=(0.2,)) as client:
        assert not client.connected
        fail_flag.unlink()

        assert await wait_until(lambda: client.connected, timeout=15)


async def test_a_server_that_stays_down_gives_unavailable_not_a_hang(tmp_path):
    flag = tmp_path / "mcp-down"
    async with stub_client(flag, connect_wait=3) as client:
        pid = await server_pid(client)
        flag.touch()                          # every relaunch now crashes
        os.kill(pid, signal.SIGKILL)

        started = time.monotonic()
        with pytest.raises(UpstreamUnavailable):
            await client.get_flight_details("off_test_0")
        assert time.monotonic() - started < 10


async def test_calls_outside_start_and_stop_are_unavailable():
    client = stub_client()

    with pytest.raises(UpstreamUnavailable):
        await client.get_flight_details("off_test_0")

    await client.start()
    await client.stop()
    await client.stop()   # stopping twice is harmless

    with pytest.raises(UpstreamUnavailable):
        await client.get_flight_details("off_test_0")


def test_production_server_path_does_not_depend_on_the_working_directory():
    script = Path(default_server().args[0])

    assert script.is_absolute()
    assert script == Path(server.__file__).resolve()


# ---- the app -------------------------------------------------------------------------


async def test_app_startup_starts_the_shared_client_and_shutdown_stops_it(monkeypatch):
    client = stub_client()
    monkeypatch.setattr(handlers, "flight_mcp_client", client)

    async with lifespan(fastapi_app):
        assert client.connected
        pid = await server_pid(client)
        assert is_running(pid)

    assert not client.connected
    assert await wait_until(lambda: not is_running(pid))


async def test_app_starts_even_when_the_mcp_server_cannot(monkeypatch, fail_flag):
    client = stub_client(fail_flag)
    monkeypatch.setattr(handlers, "flight_mcp_client", client)

    async with lifespan(fastapi_app):
        assert not client.connected


async def test_mcp_down_fails_only_flight_search_and_the_rest_of_the_app_works(session, api, monkeypatch, fail_flag):
    client = stub_client(fail_flag, connect_wait=3)
    await client.start()
    monkeypatch.setattr(handlers, "flight_mcp_client", client)

    try:
        start = session.stream.last_id
        assert (await session.say("Find flights from DEL to DXB for 1 passenger")).status_code == 202
        turn = await session.turn_done(after=start)
    finally:
        await client.stop()

    # the turn completes (it did not crash); the search step failed with a clear reason
    assert turn["data"]["outcome"] == "completed"

    steps = [e["data"] for e in session.stream.of("step") if e["id"] > start]
    search_id = next(s["id"] for s in steps if s.get("tool") == "search_flights")
    finished = [s for s in steps if s["id"] == search_id and s["status"] == "failed"]
    assert finished and finished[-1]["detail"] == UNAVAILABLE

    replies = [e["data"]["text"] for e in session.stream.of("message") if e["id"] > start and e["data"]["role"] == "assistant"]
    assert any("temporarily unavailable" in text for text in replies)

    # bookings, profile and health don't depend on MCP
    assert (await api.get("/api/bookings")).status_code == 200
    assert (await api.get("/api/passengers")).status_code == 200
    assert (await api.get("/api/health")).status_code == 200
