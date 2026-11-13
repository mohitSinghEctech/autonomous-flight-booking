"""Saved passengers REST API (/api/passengers) and its effect on existing bookings."""
import uuid
from datetime import date

import pytest
from sqlalchemy import select

from app.core.settings import settings
from app.db.models import BookingPassenger, Passenger, User
from app.db.session import SessionLocal
from app.models import PaymentStatus as ProviderStatus


NEW_PASSENGER = {
    "title": "mr", "given_name": "Ravi", "family_name": "Kumar", "gender": "m",
    "born_on": "1990-01-15", "email": "ravi@example.com", "phone_number": "+12015550124",
}

ASHA_AS_BOOKED = {
    "title": "ms", "given_name": "Asha", "family_name": "Rao", "gender": "f",
    "born_on": date(1992, 4, 2), "email": "asha@example.com", "phone_number": "+12015550123",
}


async def asha_id(api) -> str:
    [asha] = (await api.get("/api/passengers")).json()["items"]
    return asha["id"]


@pytest.fixture
async def stranger():
    """Another user with a saved passenger of their own."""
    async with SessionLocal() as db:
        other = User(given_name="Other", family_name="User")
        db.add(other)
        await db.flush()
        passenger = Passenger(
            user_id=other.id, given_name="Zoe", family_name="Stranger", title="ms", gender="f",
            born_on=date(1985, 6, 1), email="zoe@example.com", phone_number="+12015550125",
        )
        db.add(passenger)
        await db.commit()
    return passenger


async def snapshot(booking_id: str) -> list[dict]:
    """What the database keeps for the booked travellers (by provider booking id)."""
    from app.db.models import Booking

    async with SessionLocal() as db:
        booking = (await db.execute(select(Booking).where(Booking.provider_booking_id == booking_id))).scalar_one()
        rows = (await db.execute(select(BookingPassenger).where(BookingPassenger.booking_id == booking.id))).scalars()
        return [
            {k: getattr(r, k) for k in ("passenger_id", *ASHA_AS_BOOKED)}
            for r in rows
        ]


# ---------------------------------------------------------------- CRUD


async def test_list_shows_only_my_passengers(api, user, stranger):
    response = await api.get("/api/passengers")

    assert response.status_code == 200
    [asha] = response.json()["items"]
    assert asha == {
        "id": asha["id"], "title": "ms", "given_name": "Asha", "family_name": "Rao", "gender": "f",
        "born_on": "1992-04-02", "email": "asha@example.com", "phone_number": "+12015550123",
    }


async def test_create_then_get(api, user):
    response = await api.post("/api/passengers", json=NEW_PASSENGER)

    assert response.status_code == 201
    created = response.json()
    assert created == {"id": created["id"], **NEW_PASSENGER}

    fetched = await api.get(f"/api/passengers/{created['id']}")
    assert fetched.status_code == 200
    assert fetched.json() == created

    names = [p["given_name"] for p in (await api.get("/api/passengers")).json()["items"]]
    assert names == ["Asha", "Ravi"]

    async with SessionLocal() as db:
        row = await db.get(Passenger, uuid.UUID(created["id"]))
    assert row.user_id == user.id


async def test_edit_changes_only_the_fields_sent(api, user):
    passenger_id = await asha_id(api)

    response = await api.patch(f"/api/passengers/{passenger_id}", json={"family_name": "Rao-Menon", "email": "asha@new.example"})

    assert response.status_code == 200
    assert response.json()["family_name"] == "Rao-Menon"
    assert response.json()["email"] == "asha@new.example"
    assert response.json()["phone_number"] == "+12015550123"
    assert (await api.get(f"/api/passengers/{passenger_id}")).json() == response.json()


async def test_empty_edit_changes_nothing(api, user):
    passenger_id = await asha_id(api)
    before = (await api.get(f"/api/passengers/{passenger_id}")).json()

    response = await api.patch(f"/api/passengers/{passenger_id}", json={})

    assert response.status_code == 200
    assert response.json() == before


async def test_delete(api, user):
    passenger_id = await asha_id(api)

    response = await api.delete(f"/api/passengers/{passenger_id}")

    assert response.status_code == 204
    assert (await api.get(f"/api/passengers/{passenger_id}")).status_code == 404
    assert (await api.get("/api/passengers")).json() == {"items": []}
    assert (await api.delete(f"/api/passengers/{passenger_id}")).status_code == 404


# ---------------------------------------------------------------- validation (same rules as the chat form)


@pytest.mark.parametrize("field, value", [
    ("phone_number", "12345"),           # wrong shape
    ("phone_number", "+447700900123"),   # right shape, number can't exist
    ("email", "not-an-email"),
    ("email", "a b@example.com"),
    ("title", "sir"),
    ("gender", "x"),
    ("given_name", ""),
    ("born_on", "yesterday"),
])
async def test_invalid_details_are_422_on_create_and_edit(api, user, field, value):
    passenger_id = await asha_id(api)

    create = await api.post("/api/passengers", json={**NEW_PASSENGER, field: value})
    edit = await api.patch(f"/api/passengers/{passenger_id}", json={field: value})

    for response in (create, edit):
        assert response.status_code == 422
        assert response.json()["error"]["code"] == "validation_error"
        assert field in response.json()["error"]["message"]

    assert len((await api.get("/api/passengers")).json()["items"]) == 1
    assert (await api.get(f"/api/passengers/{passenger_id}")).json()[field] != value


async def test_create_requires_all_details(api, user):
    incomplete = {k: v for k, v in NEW_PASSENGER.items() if k != "phone_number"}

    response = await api.post("/api/passengers", json=incomplete)

    assert response.status_code == 422
    assert "phone_number" in response.json()["error"]["message"]


@pytest.mark.parametrize("body", [{"email": None}, {"given_name": None}, {"nickname": "Ash"}, {"id": str(uuid.uuid4())}])
async def test_edit_rejects_nulls_and_unknown_fields(api, user, body):
    passenger_id = await asha_id(api)

    response = await api.patch(f"/api/passengers/{passenger_id}", json=body)

    assert response.status_code == 422
    assert (await api.get(f"/api/passengers/{passenger_id}")).json()["given_name"] == "Asha"


# ---------------------------------------------------------------- other users' passengers


async def test_someone_elses_passenger_is_404_and_untouched(api, user, stranger):
    url = f"/api/passengers/{stranger.id}"

    for response in [
        await api.get(url),
        await api.patch(url, json={"given_name": "Hacked"}),
        await api.delete(url),
    ]:
        assert response.status_code == 404
        assert response.json()["error"] == {
            "code": "passenger_not_found", "message": "Passenger not found.", "retryable": False,
        }

    async with SessionLocal() as db:
        row = await db.get(Passenger, stranger.id)
    assert row is not None
    assert row.given_name == "Zoe"


@pytest.mark.parametrize("passenger_id", [str(uuid.uuid4()), "not-a-uuid"])
async def test_unknown_or_bad_passenger_id_is_404(api, user, passenger_id):
    for response in [
        await api.get(f"/api/passengers/{passenger_id}"),
        await api.patch(f"/api/passengers/{passenger_id}", json={"given_name": "X"}),
        await api.delete(f"/api/passengers/{passenger_id}"),
    ]:
        assert response.status_code == 404
        assert response.json()["error"]["code"] == "passenger_not_found"


async def test_the_other_user_sees_only_their_own(api, user, stranger, monkeypatch):
    monkeypatch.setattr(settings, "demo_user_id", str(stranger.user_id))

    [zoe] = (await api.get("/api/passengers")).json()["items"]
    assert zoe["given_name"] == "Zoe"


async def test_cors_allows_edit_and_delete(api):
    for method in ("PATCH", "DELETE"):
        response = await api.options(
            "/api/passengers/x",
            headers={"Origin": "http://localhost:5055", "Access-Control-Request-Method": method},
        )
        assert response.status_code == 200
        assert method in response.headers["access-control-allow-methods"]


# ---------------------------------------------------------------- existing bookings are never rewritten


async def test_booking_keeps_the_details_it_was_booked_with_after_an_edit(session, api, fakes):
    booking = await session.until_booked()
    booking_uuid = (await api.get("/api/bookings")).json()["items"][0]["id"]
    passenger_id = await asha_id(api)

    edited = await api.patch(
        f"/api/passengers/{passenger_id}",
        json={"given_name": "Ashwini", "family_name": "Menon", "email": "ash@new.example", "phone_number": "+12015550199"},
    )
    assert edited.status_code == 200

    detail = (await api.get(f"/api/bookings/{booking_uuid}")).json()
    assert detail["passengers"] == [{"id": passenger_id, "given_name": "Asha", "family_name": "Rao"}]
    assert await snapshot(booking["booking_id"]) == [{"passenger_id": uuid.UUID(passenger_id), **ASHA_AS_BOOKED}]


async def test_booking_survives_deleting_its_passenger(session, api, fakes):
    booking = await session.until_booked()
    booking_uuid = (await api.get("/api/bookings")).json()["items"][0]["id"]
    passenger_id = await asha_id(api)
    before = (await api.get(f"/api/bookings/{booking_uuid}")).json()

    assert (await api.delete(f"/api/passengers/{passenger_id}")).status_code == 204

    after = (await api.get(f"/api/bookings/{booking_uuid}")).json()
    assert [(p["given_name"], p["family_name"]) for p in after["passengers"]] == [("Asha", "Rao")]
    assert {k: v for k, v in after.items() if k != "passengers"} == {k: v for k, v in before.items() if k != "passengers"}
    assert (await api.get("/api/bookings")).json()["items"][0]["booking_id"] == booking["booking_id"]
    assert await snapshot(booking["booking_id"]) == [{"passenger_id": None, **ASHA_AS_BOOKED}]


async def test_paying_after_the_passenger_was_deleted_still_works(session, api, fakes):
    """The chat + payment flow reads the travellers from the booking, not the saved passengers."""
    await session.until_booked()
    await api.delete(f"/api/passengers/{await asha_id(api)}")

    start = session.stream.last_id
    assert (await session.api.post(session.url("/payments"))).status_code == 202
    payment = (await session.stream.wait_for("payment.updated", after=start, where=lambda p: p is not None))["data"]
    shown = (await session.stream.wait_for("booking.updated", after=start))["data"]
    await session.turn_done(after=start)

    assert [p["name"] for p in shown["passengers"]] == ["Asha Rao"]
    assert shown["lifecycle"] == "awaiting_payment"

    fakes.payments.statuses[payment["payment_id"]] = ProviderStatus.PAID
    start = session.stream.last_id
    assert (await session.api.post(session.url(f"/payments/{payment['payment_id']}/sync"))).status_code == 202
    confirmed = await session.stream.wait_for("booking.updated", after=start, where=lambda b: b["lifecycle"] == "confirmed")
    assert [p["name"] for p in confirmed["data"]["passengers"]] == ["Asha Rao"]


async def test_cancelling_after_the_passenger_was_edited_shows_the_booked_name(session, api, fakes):
    await session.until_booked()
    await api.patch(f"/api/passengers/{await asha_id(api)}", json={"given_name": "Renamed"})

    start = session.stream.last_id
    assert (await session.api.post(session.url("/booking/cancel"))).status_code == 202
    approval = (await session.stream.wait_for("approval.required", after=start))["data"]
    await session.turn_done(after=start)

    assert [p["name"] for p in approval["passengers"]] == ["Asha Rao"]

    start = session.stream.last_id
    await session.approve(approval["approval_id"])
    cancelled = await session.stream.wait_for("booking.updated", after=start, where=lambda b: b and b["lifecycle"] == "cancelled")
    assert [p["name"] for p in cancelled["data"]["passengers"]] == ["Asha Rao"]
    await session.turn_done(after=start)


async def test_new_bookings_use_the_edited_details(session, api, fakes):
    passenger_id = await asha_id(api)
    await api.patch(f"/api/passengers/{passenger_id}", json={"given_name": "Ashwini"})

    approval = await session.until_approval()
    assert [p["name"] for p in approval["passengers"]] == ["Ashwini Rao"]

    start = session.stream.last_id
    await session.approve(approval["approval_id"])
    held = await session.stream.wait_for("booking.updated", after=start, where=lambda b: b and b["lifecycle"] == "held")
    await session.turn_done(after=start)

    assert held["data"]["passengers"] == [{"id": passenger_id, "name": "Ashwini Rao"}]


# ---------------------------------------------------------------- delete while a payment is open (409 passenger_in_use)


async def open_checkout(session) -> dict:
    """Book, then start paying: the booking is now awaiting payment (fake deadline: days ahead)."""
    booking = await session.until_booked()
    start = session.stream.last_id
    assert (await session.api.post(session.url("/payments"))).status_code == 202
    payment = (await session.stream.wait_for("payment.updated", after=start, where=lambda p: p is not None))["data"]
    await session.stream.wait_for("booking.updated", after=start, where=lambda b: b["lifecycle"] == "awaiting_payment")
    await session.turn_done(after=start)
    return {**booking, "payment_id": payment["payment_id"]}


async def set_booking(provider_booking_id: str, **values) -> None:
    from app.db.models import Booking

    async with SessionLocal() as db:
        booking = (await db.execute(select(Booking).where(Booking.provider_booking_id == provider_booking_id))).scalar_one()
        for key, value in values.items():
            setattr(booking, key, value)
        await db.commit()


async def test_delete_is_409_while_a_payment_is_open(session, api, fakes):
    booking = await open_checkout(session)
    passenger_id = await asha_id(api)

    response = await api.delete(f"/api/passengers/{passenger_id}")

    assert response.status_code == 409
    error = response.json()["error"]
    assert error["code"] == "passenger_in_use"
    assert booking["booking_reference"] in error["message"]
    assert error["retryable"] is False
    assert (await api.get(f"/api/passengers/{passenger_id}")).status_code == 200
    assert (await snapshot(booking["booking_id"]))[0]["passenger_id"] == uuid.UUID(passenger_id)


async def test_edit_is_still_allowed_while_a_payment_is_open(session, api, fakes):
    await open_checkout(session)
    passenger_id = await asha_id(api)

    response = await api.patch(f"/api/passengers/{passenger_id}", json={"email": "asha@new.example"})

    assert response.status_code == 200


async def test_delete_is_allowed_once_the_payment_deadline_has_passed(session, api, fakes):
    from datetime import datetime, timedelta, timezone

    booking = await open_checkout(session)
    passenger_id = await asha_id(api)
    assert (await api.delete(f"/api/passengers/{passenger_id}")).status_code == 409

    await set_booking(booking["booking_id"], payment_required_by=datetime.now(timezone.utc) - timedelta(minutes=1))

    assert (await api.delete(f"/api/passengers/{passenger_id}")).status_code == 204


async def test_delete_is_allowed_when_the_open_payment_has_no_deadline(session, api, fakes):
    booking = await open_checkout(session)
    await set_booking(booking["booking_id"], payment_required_by=None)

    assert (await api.delete(f"/api/passengers/{await asha_id(api)}")).status_code == 204


async def test_delete_is_allowed_while_the_booking_is_only_held(session, api, fakes):
    booking = await session.until_booked()
    assert booking["lifecycle"] == "held"

    assert (await api.delete(f"/api/passengers/{await asha_id(api)}")).status_code == 204


async def test_delete_is_allowed_once_paid(session, api, fakes):
    booking = await open_checkout(session)
    fakes.payments.statuses[booking["payment_id"]] = ProviderStatus.PAID
    start = session.stream.last_id
    await session.api.post(session.url(f"/payments/{booking['payment_id']}/sync"))
    await session.stream.wait_for("booking.updated", after=start, where=lambda b: b["lifecycle"] == "confirmed")

    assert (await api.delete(f"/api/passengers/{await asha_id(api)}")).status_code == 204


@pytest.mark.parametrize("status", ["CANCELLED", "EXPIRED", "TICKETING_FAILED"])
async def test_delete_is_allowed_when_the_booking_is_no_longer_payable(session, api, fakes, status):
    from app.db.models import BookingStatus

    booking = await open_checkout(session)
    await set_booking(booking["booking_id"], status=BookingStatus[status])

    assert (await api.delete(f"/api/passengers/{await asha_id(api)}")).status_code == 204


async def test_someone_elses_passenger_in_checkout_is_still_404(session, api, fakes, monkeypatch):
    """Ownership is checked before 'in use', so a 409 never reveals someone else's passenger."""
    await open_checkout(session)
    passenger_id = await asha_id(api)

    monkeypatch.setattr(settings, "demo_user_id", str(uuid.uuid4()))

    response = await api.delete(f"/api/passengers/{passenger_id}")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "passenger_not_found"


async def test_passengers_not_on_the_open_booking_can_be_deleted(session, api, fakes):
    await open_checkout(session)
    ravi = (await api.post("/api/passengers", json=NEW_PASSENGER)).json()

    assert (await api.delete(f"/api/passengers/{ravi['id']}")).status_code == 204


# ---------------------------------------------------------------- requested scenarios


ASHA_FIELDS = {
    "title": "ms", "given_name": "Asha", "family_name": "Rao", "gender": "f",
    "born_on": "1992-04-02", "email": "asha@example.com", "phone_number": "+12015550123",
}


@pytest.fixture
async def second_user():
    """A second, real user with no passengers of their own."""
    async with SessionLocal() as db:
        other = User(given_name="Second", family_name="User")
        db.add(other)
        await db.commit()
    return other


async def test_new_passenger_create_list_get_rename_delete(api, user):
    # 1. create: 201, an id plus exactly the fields that were sent
    created = await api.post("/api/passengers", json=NEW_PASSENGER)
    assert created.status_code == 201
    new = created.json()
    assert new["id"]
    assert {k: v for k, v in new.items() if k != "id"} == NEW_PASSENGER

    # list: 200, two passengers, Asha and the new one
    listed = await api.get("/api/passengers")
    assert listed.status_code == 200
    items = listed.json()["items"]
    assert len(items) == 2
    assert {(p["given_name"], p["family_name"]) for p in items} == {("Asha", "Rao"), ("Ravi", "Kumar")}
    assert new["id"] in {p["id"] for p in items}

    # get by id: 200, the same fields that were added
    fetched = await api.get(f"/api/passengers/{new['id']}")
    assert fetched.status_code == 200
    assert fetched.json() == new

    # rename to Pooja: 200, every other field unchanged
    renamed = await api.patch(f"/api/passengers/{new['id']}", json={"given_name": "Pooja"})
    assert renamed.status_code == 200
    assert renamed.json() == {**new, "given_name": "Pooja"}
    assert (await api.get(f"/api/passengers/{new['id']}")).json() == {**new, "given_name": "Pooja"}

    # delete: 204, then it's gone
    assert (await api.delete(f"/api/passengers/{new['id']}")).status_code == 204
    gone = await api.get(f"/api/passengers/{new['id']}")
    assert gone.status_code == 404
    assert gone.json()["error"]["code"] == "passenger_not_found"


async def test_only_the_owner_can_get_edit_or_delete_asha(api, user, second_user, monkeypatch):
    # current owner
    assert settings.demo_user_id == str(user.id)
    passenger_id = await asha_id(api)
    owned = await api.get(f"/api/passengers/{passenger_id}")
    assert owned.status_code == 200
    assert {k: v for k, v in owned.json().items() if k != "id"} == ASHA_FIELDS

    # as the second user: everything is 404
    monkeypatch.setattr(settings, "demo_user_id", str(second_user.id))
    url = f"/api/passengers/{passenger_id}"
    assert (await api.get(url)).status_code == 404
    assert (await api.patch(url, json={"given_name": "Pooja"})).status_code == 404
    assert (await api.delete(url)).status_code == 404

    # back as the owner: Asha is unchanged
    monkeypatch.setattr(settings, "demo_user_id", str(user.id))
    again = await api.get(url)
    assert again.status_code == 200
    assert again.json() == owned.json()


async def test_booking_still_shows_asha_after_renaming_her_to_pooja(session, api, fakes):
    await session.until_booked()
    passenger_id = await asha_id(api)

    renamed = await api.patch(f"/api/passengers/{passenger_id}", json={"given_name": "Pooja"})
    assert renamed.status_code == 200
    assert renamed.json()["given_name"] == "Pooja"

    bookings = await api.get("/api/bookings")
    assert bookings.status_code == 200
    booking_id = bookings.json()["items"][0]["id"]

    detail = await api.get(f"/api/bookings/{booking_id}")
    assert detail.status_code == 200
    [traveller] = detail.json()["passengers"]
    assert traveller["given_name"] == "Asha"
    assert traveller["family_name"] == "Rao"


async def test_booking_still_shows_asha_after_deleting_her(session, api, fakes):
    await session.until_booked()

    assert (await api.delete(f"/api/passengers/{await asha_id(api)}")).status_code == 204

    bookings = await api.get("/api/bookings")
    assert bookings.status_code == 200
    booking_id = bookings.json()["items"][0]["id"]

    detail = await api.get(f"/api/bookings/{booking_id}")
    assert detail.status_code == 200
    [traveller] = detail.json()["passengers"]
    assert traveller["given_name"] == "Asha"
    assert traveller["family_name"] == "Rao"
