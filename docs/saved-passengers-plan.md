# Saved passengers CRUD — plan

## What's wrong today (why CRUD can't just be bolted on)

`booking_passengers` stores only `passenger_id` (FK, NOT NULL, no ON DELETE).
Every place that shows a booking's travellers re-reads the **live** `passengers`
row through that FK:

- `BookingService.booking_passengers()` → used by runner (payment start/sync,
  webhook, cancel approval, cancel finish) and agent handlers (create/complete payment)
- `GET /api/bookings/{id}` (account.py)
- `handle_book_flight` (re-fetches by id right after booking)

So with naive CRUD:

- **edit** a saved passenger → every past booking silently shows the new name;
- **delete** a saved passenger that was ever booked → FK violation (500).

## Database changes (app/db/models.py + one Alembic migration)

1. `BookingPassenger` gets a snapshot of the traveller as booked:
   `title, given_name, family_name, gender, born_on, email, phone_number`.
   Written once, in `BookingRepository.create_booking`, from the validated
   passengers that were sent to the airline. Never updated after that.
2. `BookingPassenger.passenger_id` → nullable, FK `ON DELETE SET NULL`.
   The link to the saved passenger is kept while it exists (provenance), and
   deleting the saved passenger just unlinks it. The booking keeps its snapshot.
   `Passenger.booking_passengers` uses `passive_deletes=True` so the ORM leaves
   that to the database instead of loading and nulling rows itself.
3. Migration (down_revision = `4479a967ab31`):
   add nullable columns → backfill from `passengers` (exact: there was no edit
   path before, so current values are the booked values) → `given_name`/
   `family_name` NOT NULL → `passenger_id` nullable → recreate the FK with
   `ON DELETE SET NULL`. Downgrade refuses (clear error) if unlinked rows exist,
   rather than deleting booking history.

`passengers` table itself needs no change.

## Service logic (app/services/booking.py)

- `list_passengers(user)` — unchanged contract, now deterministic order.
- `get_passenger(user, id)` / `update_passenger(user, id, changes)` /
  `delete_passenger(user, id)` / `create_passenger(user, data)` — all lookups
  are `WHERE id = :id AND user_id = :user` → `PassengerNotFound` otherwise, so
  "not yours" and "doesn't exist" are indistinguishable.
- `book_flight` passes the validated domain passengers (not just ids) to
  `create_booking`, which writes the snapshot.
- `booking_passengers(booking)` returns the snapshot rows (`BookingPassenger`),
  queried by booking id (doesn't depend on what relationship was eager-loaded).

## Other call sites

- views: `passenger_view` / `booking_view` / `booking_detail_view` accept the
  snapshot rows. Displayed `id` stays the saved passenger id (unchanged UI
  contract); if it was deleted, fall back to the booking-passenger row id.
- `handle_book_flight`, `GET /api/bookings/{id}`, runner cancel approval →
  use snapshot rows.
- Approval card (`build_booking_approval`) → scope the passenger lookup to the
  current user (today it would show another user's passenger name if the LLM
  passed a foreign id; booking itself was already blocked).

## API (app/api/account.py — plain REST like /api/bookings)

| Method | Path                       | Body                | OK  |
|--------|----------------------------|---------------------|-----|
| GET    | /api/passengers            | –                   | 200 `{"items": [...]}` |
| GET    | /api/passengers/{id}       | –                   | 200 |
| POST   | /api/passengers            | `NewPassenger`      | 201 |
| PATCH  | /api/passengers/{id}       | `PassengerUpdate`   | 200 |
| DELETE | /api/passengers/{id}       | –                   | 204 |

Unknown id, malformed id, other user's id → 404 `passenger_not_found`.

Validation reuse (app/api/events.py): POST uses the existing `NewPassenger`
as-is. The phone check moves into one shared function and the email/phone
patterns into constants, used by both `NewPassenger` (behaviour + messages
unchanged) and the new partial `PassengerUpdate` (all optional, explicit
`null` rejected, unknown fields rejected).

CORS: add `PATCH`, `DELETE` to `allow_methods` (browser would block them).

## Must not change

Session/SSE endpoints, approval flow, passenger-request form flow, payments,
webhooks, cancellation, `/api/bookings*` response shapes.

## Tests

New `tests/test_saved_passengers.py`: CRUD happy paths; 422 for bad phone /
email / null / unknown field on create and edit; 404 for foreign + bad ids on
GET/PATCH/DELETE (and the other user's row is untouched); edit and delete after
booking leave `/api/bookings/{id}` unchanged; paying for a booking after its
passenger was deleted still works and shows the booked name. Full existing
suite must stay green.

## Addendum: 409 passenger_in_use on delete

`DELETE /api/passengers/{id}` is refused with 409 `passenger_in_use` only when
the passenger is on a booking that is `awaiting_payment` **and** has a
`payment_required_by` later than the database's `now()`. Everything else
deletes: held, confirmed, cancelled, expired, ticketing_failed, a passed
deadline, or no deadline at all. Ownership is checked first (someone else's
passenger is always 404). Edits are never blocked. The message names the
booking reference and deadline. No row locking: a delete racing a checkout is
harmless because bookings keep their own copy of the travellers.
