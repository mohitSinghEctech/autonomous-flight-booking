"""Account REST endpoints."""
import uuid

from app.core.settings import settings


async def test_bookings_empty_for_new_user(api, user):
    response = await api.get("/api/bookings")

    assert response.status_code == 200
    assert response.json() == {"items": [], "next_cursor": None}


async def test_bookings_list_shows_the_users_booking(session, api):
    booking = await session.until_booked()

    response = await api.get("/api/bookings")

    assert response.status_code == 200
    items = response.json()["items"]
    assert len(items) == 1
    assert items[0]["booking_id"] == booking["booking_id"]
    assert items[0]["lifecycle"] == "held"
    assert items[0]["flight"]["origin"]["airport_code"]


async def test_bookings_limit_is_validated(api, user):
    response = await api.get("/api/bookings", params={"limit": 0})

    assert response.status_code == 422


async def test_booking_detail_shows_passengers_and_payment(session, api):
    booking = await session.until_booked()
    booking_id = (await api.get("/api/bookings")).json()["items"][0]["id"]

    response = await api.get(f"/api/bookings/{booking_id}")

    assert response.status_code == 200
    detail = response.json()
    assert detail["booking_reference"] == booking["booking_reference"]
    assert [p["given_name"] for p in detail["passengers"]] == ["Asha"]
    assert detail["payment"] is None                       # not paid yet


async def test_unknown_or_bad_booking_id_is_404(api, user):
    for booking_id in ["9b2f3c1e-0000-4000-8000-000000000000", "not-a-uuid"]:
        response = await api.get(f"/api/bookings/{booking_id}")
        assert response.status_code == 404
        assert response.json()["error"]["code"] == "booking_not_found"


async def test_someone_elses_booking_is_404(session, api, monkeypatch):
    await session.until_booked()
    booking_id = (await api.get("/api/bookings")).json()["items"][0]["id"]

    monkeypatch.setattr(settings, "demo_user_id", str(uuid.uuid4()))     # now a different caller

    response = await api.get(f"/api/bookings/{booking_id}")
    assert response.status_code == 404
