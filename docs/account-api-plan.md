# Account API — implementation plan (contract v1.2, planned)

**Status:** plan only. Nothing here is implemented. The UI side is done and already calls these endpoints
(`agent-console/public/flight/src/ui/account/`); until they exist it shows "Not available yet — needs `GET /api/…`".

**Spec:** `agent-console/docs/api-contract.md` §16 · **UI mirror:** `public/flight/src/api/contract.js` (`ACCOUNT_ENDPOINTS`, typedefs)
· **Backend mirror to add:** `app/api/events.py` (step 2 below).

---

## 0. Why this is a different kind of endpoint

Everything under `/api/sessions/{thread_id}/…` is *agent* work: it returns `202` and the result arrives as SSE events.
The account screens read and edit **saved rows** — no LLM, no turn, no stream. So these are plain REST:
the response body *is* the result. That keeps them fast, testable with one HTTP call, and independent of whether a chat session exists.

They still follow every other house rule: same auth dependency, same `{"error": {code, message, retryable}}` body,
same "someone else's id → 404" rule, same Pydantic validation (including the phone-number check).

---

## 1. Endpoints per screen

| UI screen | Endpoint | Success | Errors |
|---|---|---|---|
| Bookings list | `GET /api/bookings?limit=20&cursor=<opaque>` | `200 {items: BookingSummary[], next_cursor}` | 401, 422 `validation_error` (bad cursor/limit) |
| Booking detail | `GET /api/bookings/{id}` | `200 BookingDetail` | 404 `booking_not_found` |
| Booking detail → Cancel | `POST /api/bookings/{id}/cancel` | `200 BookingDetail` | 404, 409 `booking_not_cancellable`, 502 `provider_error`, 503 `provider_unavailable` |
| Passengers list | `GET /api/passengers` | `200 {items: PassengerProfile[]}` | 401 |
| Passenger add | `POST /api/passengers` | `201 PassengerProfile` | 422 `validation_error` |
| Passenger detail | `GET /api/passengers/{id}` | `200 PassengerProfile` | 404 `passenger_not_found` |
| Passenger edit | `PATCH /api/passengers/{id}` | `200 PassengerProfile` | 404, 422 |
| Passenger delete | `DELETE /api/passengers/{id}` | `204` | 404, 409 `passenger_in_use` |
| Profile | `GET /api/me` | `200 Me` | 401 |
| Profile → save name | `PATCH /api/me` | `200 Me` | 422 |
| *(later)* Booking detail → Pay | `POST /api/bookings/{id}/payments` | see §8 | — |

`{id}` is always **our DB uuid**. Why not the provider id like the chat events use? `provider_booking_id` is nullable and has no
unique constraint, and passengers have no provider id at all. The uuid is unguessable and every lookup is filtered by owner anyway.
The response still carries `booking_id` (provider id) so the UI can match it against the chat's `booking.updated`.

---

## 2. JSON shapes (add these Pydantic models to `app/api/events.py`)

```python
# ---- v1.2 account REST (contract §16) ----

class PassengerRef(BaseModel):                 # on a booking
    id: str
    given_name: str
    family_name: str

class AccountPayment(BaseModel):               # NO checkout block: this is history, not a payment UI
    payment_id: str                            # Cashfree order id (same meaning as Payment.payment_id)
    status: PaymentStatus
    amount: float
    currency: str
    paid_at: str | None = None

class BookingSummary(BaseModel):
    id: str                                    # our uuid
    booking_id: str | None                     # provider id
    booking_reference: str
    lifecycle: Literal["held", "awaiting_payment", "confirmed", "cancelled", "expired", "ticketing_failed"]
    total_amount: float
    currency: str
    payment_required_by: str | None            # UTC ISO
    created_at: str                            # UTC ISO
    flight: FlightView                         # views.flight_from_booking(row)

class BookingDetail(BookingSummary):
    passengers: list[PassengerRef]
    payment: AccountPayment | None

class BookingPage(BaseModel):
    items: list[BookingSummary]
    next_cursor: str | None

class PassengerProfile(BaseModel):
    id: str
    title: str | None
    given_name: str
    family_name: str
    gender: str | None
    born_on: date | None
    email: str | None
    phone_number: str | None
    complete: bool                             # all 7 fields present -> bookable
    booking_count: int

class PassengerPatch(BaseModel):               # every field optional; same rules as NewPassenger
    title: Literal["mr", "ms", "mrs", "miss", "dr"] | None = None
    given_name: str | None = Field(default=None, min_length=1, max_length=100)
    ...                                        # same Field()s as NewPassenger, each `| None = None`
    # reuse the phone validator: move NewPassenger.real_phone_number into a module-level
    # function `check_phone(value)` and call it from both models' @field_validator

class Me(BaseModel):
    id: str
    given_name: str
    family_name: str
    email: str | None                          # from the token claims, never stored

class MePatch(BaseModel):
    given_name: str | None = Field(default=None, min_length=1, max_length=100)
    family_name: str | None = Field(default=None, min_length=1, max_length=100)
```

- `POST /api/passengers` takes the existing **`NewPassenger`** unchanged — that's why the UI form and the chat form are the same component.
- Add `"booking_not_found", "booking_not_cancellable", "passenger_not_found", "passenger_in_use"` to the `ErrorCode` Literal.
- `PATCH` uses `body.model_dump(exclude_unset=True)` so omitted fields are untouched; sending `null` for a required column
  (`given_name`) must 422 — add a `model_validator` that rejects explicit `None` for `given_name`/`family_name`.

Example `GET /api/bookings` response:

```json
{
  "items": [{
    "id": "3f0c…", "booking_id": "ord_0000AbC", "booking_reference": "RZPQ7K",
    "lifecycle": "held", "total_amount": 412.6, "currency": "GBP",
    "payment_required_by": "2026-10-16T09:00:00+00:00", "created_at": "2026-10-15T08:12:03+00:00",
    "flight": { "flight_id": "off_…", "flight_name": "Emirates", "origin": {"airport_code": "DEL", "airport_name": "…"},
                "destination": {"airport_code": "DXB", "airport_name": "…"},
                "departure_datetime": "2026-11-02T06:55:00", "arrival_datetime": "2026-11-02T09:10:00",
                "price": 412.6, "currency": "GBP", "cabin": "economy", "duration_minutes": null, "expires_at": null, "stops": [] }
  }],
  "next_cursor": "MjAyNi0xMC0xNVQwODoxMjowMy4wMDBaJDNmMGM…"
}
```

---

## 3. Auth and ownership

| Rule | How | Why |
|---|---|---|
| Every endpoint needs a user | `user_id: str = Depends(current_user_id)` (exists, `app/api/auth.py`) | same as the session routes |
| Someone else's booking/passenger → **404**, never 403 | load by id, then `if row is None or row.user_id != uuid.UUID(user_id): raise ApiError(404, "booking_not_found", "Booking not found.")` | 403 would confirm the id exists (same reasoning as `session_not_found`) |
| Malformed uuid in the path → **404** too | `try: uuid.UUID(id) except ValueError: raise ApiError(404, …)` | don't leak "valid format" vs "exists"; a 422 for a typo is also unhelpful in the UI |
| Soft-deleted passenger → 404 | filter `deleted_at IS NULL` | deleted means gone for the API |
| `/api/me` email | needs the token claims, which `current_user_id` throws away. Add a sibling dependency `current_claims()` that returns `verify_token(...)` claims (or `{}` in `AUTH_MODE=demo`) and read `claims.get("email")` | email lives in Firebase, not our DB; don't store a copy that can go stale |

---

## 4. Repository / service methods: exist vs add

| Need | Exists? | Where / what to add |
|---|---|---|
| Get booking by uuid (+ passengers, payments eager-loaded) | ✅ `BookingRepository.get_booking` | — |
| List a user's bookings newest first | ⚠️ `BookingRepository.get_user_bookings` (no limit, no cursor) | add `list_user_bookings(user_id, limit, before: tuple[datetime, UUID] \| None)` — keyset pagination (§7) |
| Update booking status | ✅ `BookingRepository.update_status` | — |
| Cancel at provider + mark cancelled, idempotent, owner-checked | ✅ `BookingService.cancel_booking` | change its "not found" / "can't cancel" `AppError`s to specific exceptions (`BookingNotFound`, `BookingNotCancellable` in `app/core/errors.py`) so the route can map them to 404 / 409 |
| Booking's passengers | ✅ `BookingService.booking_passengers` | — |
| Latest payment of a booking | ✅ `PaymentRepository.get_latest_for_booking` (or `booking.payments`, already eager-loaded) | — |
| Lazy expiry | ❌ | add `BookingService.expire_if_overdue(booking)` (§6) |
| Get one passenger | ✅ `PassengerRepository.get_passenger` | add `deleted_at IS NULL` filter (after migration) |
| List a user's passengers | ✅ `get_passengers_by_user` | add `deleted_at IS NULL` + `order_by(given_name, family_name)` |
| Create passenger | ✅ `create_passenger` / `BookingService.add_passengers` | — |
| Update passenger | ❌ | add `PassengerRepository.update_passenger(passenger, **fields)` (setattr loop + flush) |
| Soft-delete passenger | ❌ | add `PassengerRepository.soft_delete(passenger)` (sets `deleted_at = now()`) |
| Booking count / "in use" check | ❌ | add `PassengerRepository.booking_counts(ids) -> dict[UUID, int]` (one `GROUP BY` over `booking_passengers`) and `is_on_active_booking(passenger_id) -> bool` (join bookings where status in HELD/AWAITING_PAYMENT) |
| Get / update user | ⚠️ `UserRepository.get_user` exists | add `UserRepository.update_names(user, given_name, family_name)` |
| Shapes | ⚠️ `views.flight_from_booking` exists | add `views.booking_summary_view`, `booking_detail_view`, `passenger_profile_view`, `me_view` |

Put the passenger CRUD in a new small **`app/services/passengers.py` → `PassengerService`** rather than growing `BookingService`:
it has its own rules (in-use check, soft delete) and no provider calls.

---

## 5. Validation

- **Passengers:** reuse `NewPassenger` for POST; `PassengerPatch` for PATCH with the *same* Field constraints and the *same*
  `phonenumbers` check (extract it into one function so the two can't drift). Duffel rejects reserved/impossible numbers,
  so catching them on save is better than failing at booking time.
- **`born_on`:** add one rule to both models: not in the future (`born_on <= date.today()`). The UI already enforces it with `max=`.
- **Names on `/me`:** `min_length=1, max_length=100` (matches `users.given_name` `String(100)`); strip whitespace.
- **Query params:** `limit: int = Query(20, ge=1, le=50)`; invalid `cursor` → `ApiError(422, "validation_error", "Invalid cursor.")`.
- Validation errors already come out as `422 {"error": {"code": "validation_error", "message": "phone_number: …"}}` via
  `install_error_handlers` — the UI shows that message under the form as-is.

---

## 6. Booking rules

### Cancel (`POST /api/bookings/{id}/cancel`)

| Current state | Result | Why |
|---|---|---|
| `held`, `awaiting_payment` | provider `cancel_order`, then `CANCELLED`; `200 BookingDetail` | same as the chat's cancel, minus the approval (the UI asks "Are you sure?" itself) |
| `cancelled` | `200` same body, **no provider call** | idempotent: a double-click or retry is harmless (`cancel_booking` already returns early) |
| `confirmed`, `expired`, `ticketing_failed` | `409 booking_not_cancellable` "Paid bookings need a refund." | paid money can't be released by a hold cancel |
| `held` but payment `pending` at Cashfree | **409 `booking_not_cancellable`** "A payment is in progress." | otherwise the user could pay for a cancelled seat; let the payment settle first |
| provider timeout / 5xx | 503 / 502 via `to_error_code`, status unchanged | never mark cancelled unless the provider agreed |

If a chat session currently shows this booking, also publish `booking.updated` to it so the chat pane doesn't show a stale "held".
Simplest: look up `chat_sessions` for this user whose `state->'booking'->>'booking_id' = provider_booking_id` and publish via the event bus.
This is optional for v1 (the UI re-reads the session snapshot on reconnect) — do it as the last step.

### Lazy expiry

Duffel holds expire at `payment_required_by`; nothing tells us. So whenever a booking is **read** by these endpoints:

```python
async def expire_if_overdue(self, booking) -> bool:
    if booking.status in (HELD, AWAITING_PAYMENT) and booking.payment_required_by and booking.payment_required_by < now_utc():
        await self.booking_repository.update_status(booking.id, BookingStatus.EXPIRED)
        return True
```

Call it in list (for each row on the page; commit once) and in detail/cancel *before* the state check (an expired booking → 409 on cancel).
Why lazy instead of a cron job: no scheduler to run, and the status is correct exactly when someone looks.
Edge: `AWAITING_PAYMENT` with a Cashfree payment that is actually `paid` but the webhook is late — leave a TODO to call
`PaymentService.sync_payment` first in that case; for v1, expire only when the latest payment is not `pending`.

---

## 7. Pagination

Keyset (cursor) pagination on `(created_at DESC, id DESC)`:

- cursor = base64url of `"<created_at ISO>|<uuid>"` of the last item on the page.
- next page: `WHERE (created_at, id) < (:created_at, :id)` → `sqlalchemy.tuple_(Booking.created_at, Booking.id) < (…)`.
- fetch `limit + 1` rows; if you got the extra one, there is a next page.

Why not `OFFSET`: new bookings arriving while you scroll would shift pages and duplicate rows; keyset is stable and uses the index.
Add an index `ix_bookings_user_created (user_id, created_at DESC, id DESC)` (§9).

Passengers are **not** paginated (a user has a handful); return `{items}` so pagination can be added later without breaking the shape.

---

## 8. Paying from the account page (not in this round)

The UI's "Pay now" currently works only when the booking is the current chat session's booking (it reuses
`POST /sessions/{t}/payments` and the payment sheet). For any other held booking the button is disabled with a TODO.
Later: `POST /api/bookings/{id}/payments` → reuse `PaymentService.create_payment(user_id, booking_id)` and return
`{payment: Payment}` **with** the `checkout` block, synchronously. Not planned now because it needs the sheet to work without a session.

---

## 9. Passenger delete

`booking_passengers.passenger_id` is a plain FK (no `ON DELETE`), so a hard `DELETE` of a passenger who was ever booked fails with an
IntegrityError, and even if it didn't, past bookings would lose their traveller names.

| Passenger is on… | Result |
|---|---|
| no booking | soft delete → `204` |
| only finished bookings (confirmed / cancelled / expired / ticketing_failed) | soft delete → `204`; history still shows the name |
| a `held` / `awaiting_payment` booking | `409 passenger_in_use` "Cancel or finish booking RZPQ7K first." |
| already deleted / not yours | `404 passenger_not_found` |

Idempotency: a second DELETE returns 404 — acceptable (the UI navigates away after the first 204).

Also make the **agent** respect it: `get_passengers_by_user` (used by `list_passengers` / the passenger-required flow)
must filter `deleted_at IS NULL`, or ATLAS will keep offering a deleted traveller. `get_passengers_by_ids` must **not** filter,
so old bookings still resolve their names.

---

## 10. Migration (one Alembic revision)

`alembic revision -m "passenger soft delete and booking list index"`:

```python
op.add_column("passengers", sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True))
op.create_index("ix_passengers_user_id_active", "passengers", ["user_id"], postgresql_where=sa.text("deleted_at IS NULL"))
op.create_index("ix_bookings_user_created", "bookings", ["user_id", sa.text("created_at DESC"), sa.text("id DESC")])
```

and `deleted_at: Mapped[datetime | None]` on `Passenger` in `app/db/models.py`. Downgrade drops both indexes and the column.
No other schema change: `users` already has the names, bookings already store a flight snapshot.

---

## 11. Status codes and error codes (summary)

| HTTP | code | When |
|---|---|---|
| 200 | — | GET, PATCH, cancel |
| 201 | — | POST /passengers (+ `Location: /api/passengers/{id}` header) |
| 204 | — | DELETE |
| 401 | `unauthenticated` | no/expired token (existing) |
| 404 | `booking_not_found` / `passenger_not_found` | missing, not yours, malformed id, soft-deleted |
| 409 | `booking_not_cancellable` | wrong state or payment pending |
| 409 | `passenger_in_use` | on an active booking |
| 422 | `validation_error` | body/query fails Pydantic (existing handler) |
| 502 / 503 | `provider_error` / `provider_unavailable` | Duffel during cancel (existing `to_error_code`) |

**Important for the UI:** an unknown route currently returns `404` with code `session_not_found` (the Starlette 404 handler).
The UI uses that to say "endpoint not available yet", and treats only `booking_not_found` / `passenger_not_found` as "this record doesn't exist".
So always use the specific codes above, never a bare `HTTPException(404)`.

---

## 12. Idempotency

| Call | Safe to retry? | How |
|---|---|---|
| GETs | yes | read-only (lazy expiry is itself idempotent) |
| cancel | yes | early return when already `CANCELLED`; take a row lock (`SELECT … FOR UPDATE`) in `cancel_booking` so two concurrent cancels don't both call Duffel |
| PATCH passenger / me | yes | full-field overwrite of what was sent |
| DELETE passenger | effectively | second call 404s, state is the same |
| POST passenger | **no** — a retry creates a duplicate | accept an optional `Idempotency-Key` header later; for v1 the UI disables the button while saving. Note it as a known gap |

---

## 13. CORS (easy to forget)

`app/main.py` has `allow_methods=["GET", "POST"]`. PATCH and DELETE preflights will be rejected and the browser reports a
network error (the UI shows "not available yet"). Change to `["GET", "POST", "PATCH", "DELETE"]`.

---

## 14. Tests to add — `tests/test_account.py`

Same harness as the rest: real uvicorn + `flight_booking_test` Postgres, `AUTH_MODE=demo`, `user` fixture (one complete passenger),
`fakes` for Duffel/Cashfree, the `api` httpx client. Use `session.until_booked()` to create a real held booking through the agent.

| Test | Asserts |
|---|---|
| `test_bookings_empty_for_new_user` | `GET /api/bookings` → `{items: [], next_cursor: null}` |
| `test_booking_appears_after_chat_booking` | after `until_booked()`: one item, `lifecycle=="held"`, `booking_id` starts `ord_fake_`, `id != booking_id` |
| `test_bookings_pagination` | insert 3 bookings directly, `limit=2` → 2 items + cursor → 1 item + `null`; no duplicates, newest first |
| `test_other_users_booking_is_404` | create a second `User` + booking in the DB; GET/cancel → 404 `booking_not_found` |
| `test_malformed_id_is_404` | `GET /api/bookings/not-a-uuid` → 404 |
| `test_cancel_held_booking` | 200, `lifecycle=="cancelled"`, `fakes.flights` recorded one cancel |
| `test_cancel_twice_calls_provider_once` | second cancel 200, still one provider cancel |
| `test_cancel_confirmed_is_409` | set status CONFIRMED in DB → 409 `booking_not_cancellable` |
| `test_overdue_hold_reads_as_expired` | set `payment_required_by` in the past → GET shows `expired`, DB row updated |
| `test_passenger_crud` | POST 201 → GET → PATCH email → list contains it → DELETE 204 → GET 404 → list no longer contains it |
| `test_passenger_bad_phone_is_422` | `+15550000000`-style reserved number → 422 `validation_error`, message mentions phone |
| `test_patch_null_name_is_422` | `{"given_name": null}` → 422 |
| `test_delete_passenger_on_held_booking_is_409` | after `until_booked()`, delete Asha → 409 `passenger_in_use` |
| `test_deleted_passenger_not_offered_to_agent` | soft-delete, then ask for 1 passenger → `passenger.required` (Asha no longer in `existing`) |
| `test_deleted_passenger_name_kept_on_old_booking` | cancel booking, delete Asha → booking detail still lists "Asha Rao" |
| `test_me_get_and_patch` | GET names; PATCH → persisted; email `null` in demo mode |
| `test_cors_allows_patch_delete` | `OPTIONS` preflight with `Access-Control-Request-Method: DELETE` from `http://localhost:5055` → 200 |

Plus a unit test in `tests/test_units.py` for cursor encode/decode round-trip.

---

## 15. Files to change, in order

Each step leaves the app working; run `uv run pytest -q` after each.

| # | File | Change | Why this order |
|---|---|---|---|
| 1 | `alembic/versions/<new>_passenger_soft_delete.py`, `app/db/models.py` | `passengers.deleted_at` + two indexes | schema first; everything else reads it |
| 2 | `app/core/errors.py` | `BookingNotFound`, `BookingNotCancellable`, `PassengerInUse` | services raise them, routes map them |
| 3 | `app/api/events.py` | models of §2, 4 new `ErrorCode`s, extract `check_phone`; bump `CONTRACT_VERSION` to `1.2` **only at the end** (step 11) | the contract mirror; Pydantic is the validation |
| 4 | `app/db/repositories/passengers.py` | `deleted_at` filters, `update_passenger`, `soft_delete`, `booking_counts`, `is_on_active_booking` | — |
| 5 | `app/db/repositories/bookings.py`, `users.py` | `list_user_bookings` (keyset), `update_names` | — |
| 6 | `app/services/booking.py` | specific exceptions in `cancel_booking`, row lock, pending-payment check, `expire_if_overdue` | business rules live in services, not routes |
| 7 | `app/services/passengers.py` (new) | `PassengerService`: list/get/create/update/delete with ownership + in-use rules | — |
| 8 | `app/api/views.py` | `booking_summary_view`, `booking_detail_view`, `passenger_profile_view`, `me_view` | the only place that knows DB ↔ JSON |
| 9 | `app/api/auth.py` | `current_claims` dependency (for `/me` email) | — |
| 10 | `app/api/account.py` (new) + `app/main.py` | `account = APIRouter(prefix="/api")` with the 10 routes; `include_router(account)`; CORS methods | thin routes: parse → service → view; keeps `routes.py` about sessions |
| 11 | `tests/test_account.py`, `tests/test_units.py` | §14 | — |
| 12 | `app/api/events.py` + `agent-console/public/flight/src/api/contract.js` + `agent-console/docs/api-contract.md` | set `CONTRACT_VERSION = "1.2"` in both code files; remove "planned" banners from §16 | the three-files rule: they change together, last, once it works |
| 13 | *(optional)* `app/services/booking.py` / event bus | publish `booking.updated` to the chat session after an account cancel | nice-to-have; the UI is correct without it |

Then try it live: run the API, open `http://localhost:5055/flight/#account/bookings`, and every screen should switch from
"Not available yet" to real data.
