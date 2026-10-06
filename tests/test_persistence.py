"""A restart (or redeploy) keeps the conversation; a late approval books nothing."""
import os
from datetime import datetime, timedelta, timezone

from app.agent import graph as agent_graph
from app.api.event_bus import event_bus
from app.api.sessions import session_store
from tests.sse import EventStream


def restart_api_memory(thread_id: str) -> None:
    """What a process restart loses: in-memory sessions, event history and counters."""
    session_store._sessions.pop(thread_id, None)
    event_bus._history.pop(thread_id, None)
    event_bus._next_event_id.pop(thread_id, None)


async def test_a_pending_approval_survives_a_restart_and_can_still_be_approved(api, server, user, fakes):
    url = os.environ["DATABASE_URL"]

    # 1st "process": real Postgres checkpointer, conversation paused at the approval
    async with agent_graph.postgres_checkpointer(url):
        thread_id = (await api.post("/api/sessions")).json()["thread_id"]

        async with EventStream(f"{server}/api/sessions/{thread_id}/stream") as stream:
            await stream.wait_for("session.snapshot")
            await api.post(f"/api/sessions/{thread_id}/messages",
                           json={"text": "Find flights from DEL to DXB for 1 passenger", "client_id": "client-1"})
            approval = (await stream.wait_for("approval.required"))["data"]
            await stream.wait_for("turn.completed")
            last_id_before = stream.last_id

        await session_store.flush()

    restart_api_memory(thread_id)

    # 2nd "process": new pool, new saver, empty memory — same database
    async with agent_graph.postgres_checkpointer(url):
        async with EventStream(f"{server}/api/sessions/{thread_id}/stream") as stream:
            snapshot = (await stream.wait_for("session.snapshot"))["data"]

            assert snapshot["approval"]["approval_id"] == approval["approval_id"]
            assert [m["text"] for m in snapshot["messages"]][0].startswith("Find flights")

            response = await api.post(f"/api/sessions/{thread_id}/approvals/{approval['approval_id']}",
                                      json={"decision": "approved"})
            assert response.status_code == 202

            booked = await stream.wait_for("booking.updated", where=lambda b: b and b["lifecycle"] == "held")
            await stream.wait_for("turn.completed", after=booked["id"])

    assert booked["id"] > last_id_before                 # ids keep increasing: the browser won't drop them
    assert fakes.flights.booked == [approval["flight_id"]]
    await session_store.flush()


async def test_a_retried_message_after_a_restart_is_still_deduplicated(api, session, fakes):
    await session.until_approval()
    await session_store.flush()
    client_id = next(iter(session_store.get(session.thread_id).seen_client_ids))

    restart_api_memory(session.thread_id)
    again = await session.say("Find flights from DEL to DXB for 1 passenger", client_id=client_id)

    assert again.status_code == 202
    assert again.json()["turn_id"] == "t1"                # same turn, nothing re-run


async def test_approving_after_the_offer_expired_books_nothing(session, fakes):
    approval = await session.until_approval()

    # the airline's deadline passes while the card is on screen
    session_store.get(session.thread_id).state["approval"]["expires_at"] = (
        datetime.now(timezone.utc) - timedelta(minutes=1)
    ).isoformat()

    start = session.stream.last_id
    assert (await session.approve(approval["approval_id"])).status_code == 202
    await session.turn_done(after=start)

    assert fakes.flights.attempts == []
    assert session.stream.of("approval.resolved")[-1]["data"]["decision"] == "expired"
    assert not session.stream.of("booking.updated")
