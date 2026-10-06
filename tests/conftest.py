"""
Integration test harness.

  - a separate PostgreSQL database (flight_booking_test), migrated with Alembic
  - the real FastAPI app served by a real uvicorn server on a free port
  - fake LLM / Duffel / Cashfree swapped in at the provider boundary

Run:  uv run pytest -q          (Docker Postgres must be running)
"""
import asyncio
import os
import socket
import subprocess
import uuid
from datetime import date
from pathlib import Path

# ---- environment BEFORE the app is imported -------------------------------------------
TEST_DB = "flight_booking_test"
BASE_URL = "postgresql+asyncpg://flight_user:flight_password@localhost:5432"
os.environ["DATABASE_URL"] = f"{BASE_URL}/{TEST_DB}"
os.environ["DB_NULL_POOL"] = "1"
os.environ.setdefault("FLIGHT_VENDOR_TOKEN", "test-token")
os.environ.setdefault("LLM_API_KEY", "test-key")
os.environ.setdefault("LLM_MODEL", "fake-model")
os.environ["LOG_LEVEL"] = "WARNING"

import asyncpg  # noqa: E402
import httpx  # noqa: E402
import pytest  # noqa: E402
import uvicorn  # noqa: E402

from app.agent import handlers, llm  # noqa: E402
from app.api import routes  # noqa: E402
from app.db.models import Passenger, User  # noqa: E402
from app.db.session import SessionLocal  # noqa: E402
from app.main import app  # noqa: E402
from app.providers import all_providers  # noqa: E402
from tests.fakes import FakeFlightProvider, FakeLLM, FakeMCPClient, FakePaymentProvider  # noqa: E402
from tests.sse import EventStream  # noqa: E402

PROJECT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="session", autouse=True)
def test_database():
    """Create flight_booking_test once and migrate it to head."""

    async def create():
        conn = await asyncpg.connect(f"{BASE_URL.replace('+asyncpg', '')}/postgres")
        try:
            exists = await conn.fetchval("SELECT 1 FROM pg_database WHERE datname = $1", TEST_DB)
            if not exists:
                await conn.execute(f'CREATE DATABASE "{TEST_DB}"')
        finally:
            await conn.close()

    asyncio.run(create())
    subprocess.run(["uv", "run", "alembic", "upgrade", "head"], cwd=PROJECT, check=True, env=os.environ.copy(),
                   capture_output=True)


@pytest.fixture
def fakes(monkeypatch):
    flights = FakeFlightProvider()
    payments = FakePaymentProvider()
    model = FakeLLM()

    monkeypatch.setattr(all_providers, "flight_provider", flights)
    monkeypatch.setattr(all_providers, "payment_provider", payments)
    monkeypatch.setattr(handlers, "flight_mcp_client", FakeMCPClient(flights))
    monkeypatch.setattr(llm, "client", model)

    class Fakes:
        pass

    bag = Fakes()
    bag.flights, bag.payments, bag.llm = flights, payments, model
    return bag


@pytest.fixture
async def user(monkeypatch):
    """A fresh user with ONE complete saved passenger; sessions belong to them."""

    async with SessionLocal() as session:
        account = User(given_name="Test", family_name="User")
        session.add(account)
        await session.flush()

        session.add(Passenger(
            user_id=account.id, given_name="Asha", family_name="Rao", title="ms", gender="f",
            born_on=date(1992, 4, 2), email="asha@example.com", phone_number="+919800000001",
        ))
        await session.commit()

    monkeypatch.setattr(routes, "DEMO_USER_ID", str(account.id))
    return account


@pytest.fixture
async def server():
    """The real app on a real socket, so SSE behaves exactly as in the browser."""

    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]

    config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning", lifespan="off")
    instance = uvicorn.Server(config)
    task = asyncio.create_task(instance.serve())

    while not instance.started:
        await asyncio.sleep(0.02)

    yield f"http://127.0.0.1:{port}"

    instance.should_exit = True
    instance.force_exit = True
    await asyncio.wait_for(task, timeout=5)


@pytest.fixture
async def api(server):
    async with httpx.AsyncClient(base_url=server, timeout=20) as client:
        yield client


@pytest.fixture
async def session(api, server, user, fakes):
    """A new conversation with its stream already open."""

    response = await api.post("/api/sessions")
    thread_id = response.json()["thread_id"]

    async with EventStream(f"{server}/api/sessions/{thread_id}/stream") as stream:
        await stream.wait_for("session.snapshot")
        yield Conversation(api, thread_id, stream)


class Conversation:

    def __init__(self, api: httpx.AsyncClient, thread_id: str, stream: EventStream):
        self.api = api
        self.thread_id = thread_id
        self.stream = stream

    def url(self, path: str) -> str:
        return f"/api/sessions/{self.thread_id}{path}"

    async def say(self, text: str, client_id: str | None = None) -> httpx.Response:
        return await self.api.post(self.url("/messages"), json={"text": text, "client_id": client_id or uuid.uuid4().hex})

    async def approve(self, approval_id: str, decision: str = "approved") -> httpx.Response:
        return await self.api.post(self.url(f"/approvals/{approval_id}"), json={"decision": decision})

    async def answer(self, approval_id: str, decision: str = "approved") -> httpx.Response:
        """Answer an approval and wait until the resumed turn has finished."""
        start = self.stream.last_id
        response = await self.approve(approval_id, decision)
        if response.status_code == 202:
            await self.stream.wait_for("turn.completed", after=start)
        return response

    async def turn_done(self, after: int = -1) -> dict:
        """Wait for the next turn.completed after event id `after`."""
        return await self.stream.wait_for("turn.completed", after=after)

    async def until_approval(self, text: str = "Find flights from DEL to DXB for 1 passenger") -> dict:
        start = self.stream.last_id
        response = await self.say(text)
        assert response.status_code == 202
        approval = (await self.stream.wait_for("approval.required", after=start))["data"]
        await self.stream.wait_for("turn.completed", after=start)   # the turn is fully closed
        return approval

    async def until_booked(self) -> dict:
        approval = await self.until_approval()
        start = self.stream.last_id
        assert (await self.approve(approval["approval_id"])).status_code == 202
        booking = (await self.stream.wait_for("booking.updated", after=start, where=lambda d: d and d["lifecycle"] == "held"))["data"]
        await self.stream.wait_for("turn.completed", after=start, where=lambda t: t["outcome"] == "completed")
        return booking
