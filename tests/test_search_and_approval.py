"""Chat -> search -> approval: the graph's human-in-the-loop over SSE."""


async def test_health(api):
    response = await api.get("/api/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


async def test_snapshot_is_the_first_event(session):
    first = session.stream.events[0]
    assert first["event"] == "session.snapshot"
    assert first["data"]["contract_version"] == "1.1"
    assert first["data"]["thread_id"] == session.thread_id
    assert first["data"]["status"]["busy"] is False


async def test_search_ends_in_an_approval(session, fakes):
    approval = await session.until_approval()

    # the order a browser sees
    names = [e["event"] for e in session.stream.events[1:]]
    for expected in ["message", "turn.started", "status", "step", "flights.results",
                     "flights.selected", "approval.required", "turn.completed"]:
        assert expected in names, f"missing {expected} in {names}"
    assert names.index("flights.results") < names.index("approval.required")

    # contract shape of the approval
    assert approval["kind"] == "book"
    assert approval["approval_id"].startswith("ap_")
    assert approval["flight_id"] == fakes.flights.cheapest.flight_id
    assert approval["total_amount"] == fakes.flights.cheapest.price
    assert approval["passengers"] == [{"id": approval["passengers"][0]["id"], "name": "Asha Rao"}]
    assert approval["flight"]["duration_minutes"] == 210

    # paused, not busy: the chat is open again
    completed = session.stream.of("turn.completed")[-1]["data"]
    assert completed["outcome"] == "interrupted"
    await session.stream.wait_for("status", where=lambda s: s["stage"] == "awaiting_approval")

    # nothing booked before a human said yes
    assert fakes.flights.booked == []


async def test_user_message_uses_the_client_id(session):
    await session.say("hello there", client_id="client-123")
    message = await session.stream.wait_for("message", where=lambda m: m["role"] == "user")
    assert message["data"]["id"] == "client-123"
    assert message["data"]["text"] == "hello there"
    reply = await session.stream.wait_for("message", where=lambda m: m["role"] == "assistant")
    assert reply["data"]["text"]


async def test_steps_have_contract_shape(session):
    await session.until_approval()
    started = [e["data"] for e in session.stream.of("step") if "title" in e["data"]]
    titles = [s["title"] for s in started]
    assert "Understanding your request" in titles
    assert "Searching flights" in titles
    search = next(s for s in started if s["title"] == "Searching flights")
    assert search["tool"] == "search_flights"
    assert search["kind"] == "tool"
    assert search["turn_id"]
