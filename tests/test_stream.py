"""SSE transport: ids, snapshot on reconnect, heartbeats, error shapes."""
from app.api import routes
from tests.sse import EventStream


async def test_event_ids_strictly_increase(session):
    await session.until_approval()
    ids = [e["id"] for e in session.stream.events if e["id"] is not None]
    assert ids == sorted(ids)
    assert len(ids) == len(set(ids))


async def test_reconnect_gets_a_full_snapshot(session, server):
    approval = await session.until_approval()
    last = session.stream.last_id

    # a new tab / a reconnect after a network drop
    async with EventStream(f"{server}/api/sessions/{session.thread_id}/stream", last_event_id=last) as again:
        snapshot = await again.wait_for("session.snapshot")

    state = snapshot["data"]
    assert snapshot["id"] >= last                          # the browser resumes from here
    assert state["approval"]["approval_id"] == approval["approval_id"]
    assert len(state["flights"]) == 3
    assert state["selection"]["flight_id"] == approval["flight_id"]
    assert state["status"]["stage"] == "awaiting_approval"
    assert any(m["role"] == "user" for m in state["messages"])
    assert any(t["type"] == "turn" for t in state["timeline"])


async def test_heartbeat_keeps_the_stream_alive(server, user, fakes, api, monkeypatch):
    monkeypatch.setattr(routes, "HEARTBEAT_SECONDS", 0.2)
    thread_id = (await api.post("/api/sessions")).json()["thread_id"]

    async with EventStream(f"{server}/api/sessions/{thread_id}/stream") as stream:
        await stream.wait_for("session.snapshot")
        for _ in range(30):
            if stream.comments:
                break
            import asyncio
            await asyncio.sleep(0.05)

    assert ": ping" in stream.comments


async def test_validation_errors_use_the_error_shape(session):
    response = await session.api.post(session.url("/messages"), json={"text": ""})
    assert response.status_code == 422
    body = response.json()
    assert set(body) == {"error"}
    assert body["error"]["code"] == "validation_error"
    assert body["error"]["retryable"] is False


async def test_bad_approval_body_is_422(session):
    response = await session.api.post(session.url("/approvals/x"), json={"decision": "maybe"})
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"


async def test_cors_allows_the_hosted_ui(api):
    response = await api.options(
        "/api/health",
        headers={"Origin": "https://provenance.web.app", "Access-Control-Request-Method": "GET"},
    )
    assert response.headers.get("access-control-allow-origin") == "https://provenance.web.app"
