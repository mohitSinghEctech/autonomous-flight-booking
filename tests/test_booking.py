"""Approve / reject / supersede / change / cancel — and the rules around them."""
import uuid

from sqlalchemy import select

from app.db.models import Booking, BookingStatus
from app.api import runner
from app.db.session import SessionLocal


async def db_booking(provider_booking_id: str) -> Booking:
    async with SessionLocal() as session:
        result = await session.execute(select(Booking).where(Booking.provider_booking_id == provider_booking_id))
        return result.scalar_one()


async def test_approve_holds_the_seat_and_saves_it(session, fakes):
    booking = await session.until_booked()

    assert booking["lifecycle"] == "held"
    assert booking["booking_id"].startswith("ord_fake_")          # provider id, not our uuid
    assert booking["flight_id"] == fakes.flights.cheapest.flight_id
    assert booking["passengers"][0]["name"] == "Asha Rao"
    assert fakes.flights.booked == [fakes.flights.cheapest.flight_id]

    row = await db_booking(booking["booking_id"])
    assert row.status == BookingStatus.HELD
    assert str(row.id) != booking["booking_id"]                    # the two ids never mix

    resolved = session.stream.of("approval.resolved")[-1]["data"]
    assert resolved["decision"] == "approved"


async def test_reject_books_nothing(session, fakes):
    approval = await session.until_approval()
    start = session.stream.last_id

    assert (await session.approve(approval["approval_id"], "rejected")).status_code == 202
    await session.turn_done(after=start)

    assert fakes.flights.booked == []
    assert session.stream.of("approval.resolved")[-1]["data"]["decision"] == "rejected"
    assert not session.stream.of("booking.updated")


async def test_double_click_approve_books_once(session, fakes):
    approval = await session.until_approval()

    first = await session.approve(approval["approval_id"])
    second = await session.approve(approval["approval_id"])          # same answer again

    assert first.status_code == 202
    assert second.status_code in (202, 409)                          # 409 only while the first still runs
    await session.stream.wait_for("booking.updated", where=lambda b: b and b["lifecycle"] == "held")
    await session.stream.wait_for("turn.completed", where=lambda t: t["outcome"] == "completed")

    again = await session.approve(approval["approval_id"])
    assert again.status_code == 202                                   # idempotent after it finished
    assert len(fakes.flights.booked) == 1


async def test_approval_before_it_exists_is_rejected(session):
    response = await session.approve("ap_not_real")
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "approval_not_pending"


async def test_a_different_answer_after_resolution_is_409(session):
    approval = await session.until_approval()
    await session.answer(approval["approval_id"], "rejected")

    response = await session.approve(approval["approval_id"], "approved")
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "approval_already_resolved"


async def test_new_message_supersedes_a_pending_approval(session, fakes):
    approval = await session.until_approval()
    start = session.stream.last_id

    assert (await session.say("hello again")).status_code == 202      # waiting is not busy
    await session.turn_done(after=start)

    resolved = await session.stream.wait_for("approval.resolved", after=start)
    assert resolved["data"] == {"approval_id": approval["approval_id"], "decision": "superseded"}
    assert fakes.flights.booked == []


async def test_choosing_a_flight_on_the_board(session, fakes):
    await session.until_approval()
    other = next(f for f in fakes.flights.offers if f != fakes.flights.cheapest.flight_id)
    start = session.stream.last_id

    response = await session.api.post(session.url("/flight-selection"), json={"flight_id": other})
    assert response.status_code == 202

    selected = await session.stream.wait_for("flights.selected", after=start)
    assert selected["data"] == {"flight_id": other, "by": "user", "reason": "Your choice"}
    approval = await session.stream.wait_for("approval.required", after=start)
    assert approval["data"]["flight_id"] == other


async def test_unknown_flight_selection_is_404(session):
    response = await session.api.post(session.url("/flight-selection"), json={"flight_id": "off_nope"})
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "flight_not_found"


async def test_change_releases_the_old_hold(session, fakes):
    first = await session.until_booked()
    other = next(f for f in fakes.flights.offers if f != first["flight_id"])
    start = session.stream.last_id

    await session.api.post(session.url("/flight-selection"), json={"flight_id": other})
    approval = (await session.stream.wait_for("approval.required", after=start))["data"]
    assert approval["kind"] == "change"
    await session.turn_done(after=start)

    start = session.stream.last_id
    await session.approve(approval["approval_id"])
    second = (await session.stream.wait_for("booking.updated", after=start, where=lambda b: b and b["flight_id"] == other))["data"]

    assert fakes.flights.cancelled == [first["booking_id"]]
    assert (await db_booking(first["booking_id"])).status == BookingStatus.CANCELLED
    assert (await db_booking(second["booking_id"])).status == BookingStatus.HELD


async def test_cancel_booking_needs_approval(session, fakes):
    booking = await session.until_booked()
    await session.stream.wait_for("turn.completed", where=lambda t: t["outcome"] == "completed")
    start = session.stream.last_id

    assert (await session.api.post(session.url("/booking/cancel"))).status_code == 202
    approval = (await session.stream.wait_for("approval.required", after=start))["data"]
    assert approval["kind"] == "cancel"
    assert fakes.flights.cancelled == []                              # nothing until the user says yes
    await session.turn_done(after=start)

    start = session.stream.last_id
    await session.approve(approval["approval_id"])
    cancelled = await session.stream.wait_for("booking.updated", after=start, where=lambda b: b and b["lifecycle"] == "cancelled")

    assert cancelled["data"]["booking_id"] == booking["booking_id"]
    assert fakes.flights.cancelled == [booking["booking_id"]]
    assert (await db_booking(booking["booking_id"])).status == BookingStatus.CANCELLED

    # the AGENT must know too, or its next answer says "you're already booked"
    await session.turn_done(after=start)
    values = await runner.agent_values(session.thread_id)
    assert values["booking"]["lifecycle"] == "cancelled"
    assert values["db_booking_id"] is None
    assert "CANCELLED" in values["messages"][-1]["content"]          # the history says so too


async def test_cancel_without_booking_is_409(session):
    response = await session.api.post(session.url("/booking/cancel"))
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "no_active_booking"


async def test_busy_conversation_rejects_new_work(session):
    first = await session.say("Find flights from DEL to DXB for 1 passenger")
    second = await session.say("and another thing")

    assert first.status_code == 202
    assert second.status_code == 409
    body = second.json()["error"]
    assert body == {"code": "turn_in_progress", "message": body["message"], "retryable": True}


async def test_same_client_id_runs_once(session, fakes):
    client_id = uuid.uuid4().hex
    first = await session.say("hello", client_id=client_id)
    second = await session.say("hello", client_id=client_id)           # network retry

    assert first.status_code == second.status_code == 202
    assert first.json()["turn_id"] == second.json()["turn_id"]
    await session.turn_done()
    users = [m for m in session.stream.of("message") if m["data"]["role"] == "user"]
    assert len(users) == 1


async def test_a_fare_the_airline_refused_is_never_offered_for_approval_again(session, fakes):
    dead = fakes.flights.cheapest.flight_id
    fakes.flights.gone.add(dead)

    approval = await session.until_approval()
    start = session.stream.last_id
    await session.approve(approval["approval_id"])
    await session.turn_done(after=start)

    steps = [s["data"] for s in session.stream.of("step")]
    hold_id = [s["id"] for s in steps if s.get("tool") == "book_flight"][-1]
    finished = [s for s in steps if s["id"] == hold_id and s.get("status") == "failed"][-1]
    assert finished["detail"] == "Fare no longer available"
    assert not session.stream.of("booking.updated")

    start = session.stream.last_id
    await session.say(f"Book {dead} again please")
    await session.turn_done(after=start)

    assert not [e for e in session.stream.of("approval.required") if e["id"] > start]
    assert fakes.flights.attempts == [dead]                       # the airline was asked once
