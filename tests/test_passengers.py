"""Passenger-required workflow: interrupt -> form -> Postgres -> resume -> approval."""
from sqlalchemy import select

from app.db.models import Passenger
from app.db.session import SessionLocal


NEW_PASSENGER = {
    "title": "mr", "given_name": "Ravi", "family_name": "Kumar", "gender": "m",
    "born_on": "1990-01-15", "email": "ravi@example.com", "phone_number": "+919800000002",
}


async def ask_for_two(session) -> dict:
    start = session.stream.last_id
    await session.say("Find flights from DEL to DXB for 2 passengers")
    request = (await session.stream.wait_for("passenger.required", after=start))["data"]
    await session.turn_done(after=start)
    return request


async def test_missing_passenger_pauses_for_details(session, fakes, user):
    request = await ask_for_two(session)

    assert request["request_id"].startswith("pr_")
    assert request["needed"] == 1
    assert [p["name"] for p in request["existing"]] == ["Asha Rao"]
    assert "phone_number" in request["fields"]
    assert fakes.flights.booked == []
    await session.stream.wait_for("status", where=lambda s: s["stage"] == "awaiting_approval")


async def test_providing_details_saves_them_and_continues_to_approval(session, fakes, user):
    request = await ask_for_two(session)
    start = session.stream.last_id

    response = await session.api.post(
        session.url(f"/passenger-requests/{request['request_id']}"),
        json={"decision": "provided", "passengers": [NEW_PASSENGER]},
    )
    assert response.status_code == 202

    resolved = (await session.stream.wait_for("passenger.resolved", after=start))["data"]
    assert resolved["decision"] == "provided"
    assert resolved["passengers"][0]["name"] == "Ravi Kumar"

    approval = (await session.stream.wait_for("approval.required", after=start))["data"]
    assert sorted(p["name"] for p in approval["passengers"]) == ["Asha Rao", "Ravi Kumar"]

    async with SessionLocal() as db:
        saved = (await db.execute(select(Passenger).where(Passenger.user_id == user.id))).scalars().all()
    assert {p.given_name for p in saved} == {"Asha", "Ravi"}


async def test_invalid_passenger_details_are_422(session, fakes):
    request = await ask_for_two(session)

    bad = {**NEW_PASSENGER, "phone_number": "12345"}
    response = await session.api.post(
        session.url(f"/passenger-requests/{request['request_id']}"),
        json={"decision": "provided", "passengers": [bad]},
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"
    assert "phone_number" in response.json()["error"]["message"]


async def test_wrong_passenger_count_is_422(session, fakes):
    request = await ask_for_two(session)

    response = await session.api.post(
        session.url(f"/passenger-requests/{request['request_id']}"),
        json={"decision": "provided", "passengers": [NEW_PASSENGER, NEW_PASSENGER]},
    )
    assert response.status_code == 422


async def test_cancelling_the_form_books_nothing(session, fakes):
    request = await ask_for_two(session)
    start = session.stream.last_id

    await session.api.post(session.url(f"/passenger-requests/{request['request_id']}"), json={"decision": "cancelled"})
    resolved = (await session.stream.wait_for("passenger.resolved", after=start))["data"]
    await session.turn_done(after=start)

    assert resolved["decision"] == "cancelled"
    assert fakes.flights.booked == []
    assert not [e for e in session.stream.events if e["event"] == "approval.required" and e["id"] > start]
