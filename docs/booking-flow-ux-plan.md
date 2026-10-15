# Booking-flow UX — implementation plan (contract v1.3, planned)

**Status:** plan only. Nothing here is implemented (backend or UI), except the journey bar move noted in §0.
**UI:** `agent-console/public/flight/` · **Spec:** `agent-console/docs/api-contract.md` · **UI mirror:** `src/api/contract.js`
· **Backend mirror:** `app/api/events.py`. As always: change those three together.

Four features, one theme: **a conversation is one trip.** It starts at a home form, ends when the trip is paid and
ticketed (or cancelled), and the next trip is a new conversation.

| # | Feature | Backend size | UI size |
|---|---|---|---|
| 1 | Home / search form on the left pane | S (one endpoint) | M |
| 2 | Inline passenger cards with field-level errors | M (error mapping) | M |
| 3 | Close a finished trip, start a new one, keep history (+ future pgvector) | M | S |
| 4 | Recent searches + cancel at any stage before payment completes | L (payment races) | S |

---

## 0. Already done: the journey bar belongs to the trip

The six-step indicator (Search → Choose → Approve → Hold → Pay → Confirmed, `JOURNEY` / `journeyIndex()` in
`src/state/selectors.js`) used to sit in the global top bar. It now lives in `src/ui/components/journeyBar.js`, mounted at the
top of the flights pane (`flightsPane.js`), and hides while the session has no booking flow. This matters for the features
below: **when a new session starts (#1, #3) the bar disappears on its own**, because `hasBookingFlow(state)` is false
for an empty state. No extra work needed.

---

## 1. Home state on the left pane (search form)

### 1.1 UX

| When | Left pane shows |
|---|---|
| Fresh session (no `search`, no `flights`, no `booking`) | **Home**: search form + recent searches (#4) |
| Trip finished (#3) | The user is moved to a new session → Home |
| Search running | Today's "searching" state (`searchingState()` in `flightsPane.js`) |
| Results / trip | Unchanged |

Form fields: **From**, **To** (IATA 3-letter, uppercase, with airport-name hint later), **Date** (`<input type=date min=today>`),
**Passengers** (1–9 stepper), **Cabin** (`economy | premium_economy | business | first`, same `Cabin` enum as `app/models.py`).
Submit button "Search flights" is disabled until valid (`from ≠ to`, both `^[A-Z]{3}$`, date ≥ today).
The chat stays usable: typing "DEL to DXB tomorrow" still works. The form is a shortcut, not a second path.

### 1.2 Decision: structured endpoint vs. a chat message

| Option | How | Pros | Cons |
|---|---|---|---|
| A. Send a chat message ("Find flights from DEL to DXB on 2026-11-02, 2 adults, economy") via `POST /messages` | zero backend work | LLM re-parses text you already had structured; may "improve" it (wrong date, adds booking); can't validate until the LLM runs |
| **B. `POST /api/sessions/{id}/search` with a `SearchFlights` body (recommended)** | Pydantic validates before anything runs (422 per field); exact params; the turn still goes through the agent so the conversation history says what was searched | one endpoint + one runner function |

**Recommendation: B**, modelled on `select_flight` in `app/api/routes.py` — that route already does exactly this pattern
("the LLM gets an exact instruction; the user sees a friendly line"). Do the same: validate with `SearchFlights`, publish a friendly
user bubble, then `runner.run_message(session, instruction, origin="search")` where `instruction` names the exact parameters and
says *"search only — don't book"*. This keeps one engine (the graph) and one source of truth for the conversation, and it is
cheap. (Calling `handle_search_flights` directly, skipping the LLM, is faster but then the graph's history doesn't know about
the results; revisit only if latency matters.)

### 1.3 Contract / events

| Change | Where |
|---|---|
| `SearchIn` = `SearchFlights` fields (`origin, destination, date, passengers, cabin`) | `app/api/events.py`, `contract.js` typedef, `api-contract.md` §3 |
| `POST /api/sessions/{thread_id}/search` → `202 {accepted, turn_id}`; 409 `turn_in_progress`; 409 `session_closed` (#3); 422 `validation_error` with `fields` (see §2.3) | `routes.py` |
| No new SSE event: results arrive as today's `search.*` / `flights.*` events | — |

### 1.4 Backend steps

| # | Step | File |
|---|---|---|
| 1 | Add `SearchIn` (reuse `SearchFlights` validators: date ≥ today; add `origin != destination`, upper-case IATA) | `app/api/events.py` |
| 2 | Add route `search_flights`: `get_session` → reject closed session (#3) → `lock_or_409` → publish user bubble → `start_turn(... runner.run_message(..., origin="search"))` | `app/api/routes.py` |
| 3 | Accept `origin="search"` in `runner.turn()` titles | `app/api/runner.py` |
| 4 | Record the search for "recent searches" (#4, §4.2) | `app/services/search_history.py` (new) |
| 5 | Tests: 422 on bad IATA/past date; 202 + the instruction text reaches the graph (mock graph); 409 when busy | `tests/api/test_search_route.py` |

### 1.5 UI steps

| # | Step | File |
|---|---|---|
| 1 | `homeView(state, { onSearch, onRecent })` — pure function returning the form + recent list | `src/ui/components/homeView.js` (new) |
| 2 | Show it in `flightsPane.js` when `isHome(state)` (new selector: no `search`, no `flights`, no `booking`, not busy) — replaces today's `emptyState()` | `flightsPane.js`, `selectors.js` |
| 3 | `actions.search(params)` → `transport.search(params)` → `POST /search` | `main.js`, `src/api/transport.js` |
| 4 | Cache the form element like `passengerForm.js` does, so typing survives re-renders | `homeView.js` |
| 5 | Mobile: on a fresh session default `data-tab` to `flights` so the form is visible | `reducer.js` (`ui/thread`) |

### 1.6 Edge cases

| Case | Behaviour |
|---|---|
| Submit while ATLAS is busy | button disabled (`state.status.busy`); server 409 as backstop |
| Submit while an approval / passenger request waits | the route goes through `run_message`, whose `supersede_pending()` closes the old question — same as typing |
| Session has a held booking | Home isn't shown then (left pane is in trip mode), so no conflict |
| Same city pair, different code (e.g. LHR/LGW) | allowed; only identical codes are rejected |

---

## 2. Passenger details inline, with field-level errors

### 2.1 UX

| Situation | Left pane |
|---|---|
| `passenger.required` and **no** saved passengers | one **empty** card, expanded |
| `passenger.required`, `needed = N ≥ 2` | a list of N collapsible cards; **only one expanded at a time** (accordion). Collapsed card: "Mr Rahul Sharma · 12 Mar 1990 · +91 98…" + **green tick** when valid, red dot when not |
| A saved passenger was **rejected** (Duffel or our phone check) | the card for that passenger, **pre-filled**, invalid fields outlined red (`--red`) with the message under the field; card auto-expanded |
| Any card invalid | "Save & continue" / "Update passenger" **disabled** until every field validates on the client |

Client-side validation mirrors `NewPassenger` in `app/api/events.py` (title enum, names 1–100, gender m/f, `born_on` date,
email pattern, phone `^\+[1-9]\d{7,14}$`). The client can't run `phonenumbers.is_valid_number`, so a phone that matches the
shape but doesn't exist is caught by the server and comes back as a field error (§2.3) — the card then outlines it.

Accessibility: each field gets `aria-invalid="true"` and `aria-describedby` → the error text; cards are `<details>`-like
buttons with `aria-expanded`; the tick has a text alternative ("valid").

### 2.2 How it fits the existing interrupt

Today: the LLM calls `request_passenger_details` → `passengers_node` (`app/agent/passengers.py`) builds
`{request_id, needed, existing, fields, message}` and calls `interrupt()` → `runner.handle_graph_result` publishes
`passenger.required` → UI `passengerForm.js` → `POST /passenger-requests/{id}` (`routes.add_passengers`) →
`runner.resume_passengers` saves via `BookingService.add_passengers` and resumes the graph.

Two gaps:

| Gap | Today | Needed |
|---|---|---|
| A. Server-side validation failure | FastAPI 422 for the whole body; the UI shows one error string | 422 with **per-passenger, per-field** errors |
| B. A *saved* passenger is rejected later (Duffel at `book_flight`, or `to_domain_passenger` "missing travel details") | `raise_for_duffel` turns it into one `ProviderError` string; the LLM apologises in chat | the agent must be able to **re-open** the passenger card for that passenger, with which field is wrong |

### 2.3 Contract changes (v1.3)

```text
# 422 body for POST /passenger-requests/{id}, POST /search, PATCH /passengers/{id}
{"error": {"code": "validation_error", "message": "...", "retryable": false,
           "fields": [{"index": 0, "field": "phone_number", "message": "This phone number doesn't exist."}]}}

# passenger.required gains two optional keys
{ request_id, needed, existing, fields, message,
  "mode": "add" | "fix",                       # fix = edit saved passengers
  "invalid": [{"passenger_id": "<uuid>", "field": "phone_number", "message": "..."}] }
```

| Change | Where |
|---|---|
| `FieldError {index?, passenger_id?, field, message}`; `ErrorBody.fields: list[FieldError] = []` | `app/api/events.py`, `contract.js`, `api-contract.md` §5 |
| A `RequestValidationError` handler that converts Pydantic `loc` (`["body","passengers",0,"phone_number"]`) → `FieldError(index=0, field="phone_number")` | `app/api/errors.py` |
| `PassengerRequiredEvent.mode`, `.invalid` | `events.py` |
| `PassengersIn` gains `updates: list[PassengerUpdate]` (`id` + the same fields) for `mode="fix"` | `events.py` |
| New domain error `PassengerInvalid(passenger_id, field, message)` | `app/core/errors.py` |

### 2.4 Mapping Duffel errors to a field

Duffel 422s carry `errors[].source.pointer` (e.g. `/passengers/0/phone_number`) and a `code` such as `invalid_phone_number`.
`raise_for_duffel` (`app/providers/flights/duffel.py`) currently keeps only `title`/`message`.

| # | Step |
|---|---|
| 1 | In `raise_for_duffel`, if `source.pointer` matches `/passengers/(\d+)/(\w+)`, raise `PassengerInvalid` with the passenger at that index (pass `passengers` into the helper from `book_flight`) and the field name. Keep `ProviderError` for everything else. |
| 2 | Map Duffel field names to ours (`phone_number`, `email`, `born_on`, `given_name`, `family_name`, `gender`, `title` are already the same — keep a dict anyway). |
| 3 | `to_domain_passenger` (`app/services/booking.py`) raises `PassengerInvalid` per missing field instead of one `AppError` string. |
| 4 | In the tool handler for `book_flight` (`app/agent/handlers.py`) return the error to the LLM as structured JSON `{"error":"passenger_invalid","passenger_id":..,"field":..,"message":..}` and tell it (system prompt) to call `request_passenger_details` with `fix_passenger_ids`. |
| 5 | `passengers_node`: accept `fix_passenger_ids` + `invalid` args → `mode="fix"`, `existing` = those passengers, `needed=0`. Simpler alternative (recommended, less LLM-dependent): have the **handler** stash `invalid` in agent state and route the graph straight to `passengers_node` on `PassengerInvalid` — no LLM decision needed. |
| 6 | `resume_passengers`: if `updates` present, `PassengerRepository.update_passenger` each (validated by `NewPassenger`), then resume with `{"decision":"provided","passengers":[...updated]}`; the LLM retries booking (still behind the normal approval). |

### 2.5 UI steps

| # | Step | File |
|---|---|---|
| 1 | Split `passengerForm.js` into `passengerCard(passenger, {errors, expanded, onToggle, onChange})` + `passengerList(request)` (accordion state = index of the open card) | `src/ui/components/passengerCard.js` (new), `passengerForm.js` |
| 2 | `validatePassenger(p) → {field: message}` mirroring `NewPassenger` | `src/ui/validation.js` (new) |
| 3 | Merge server errors (`invalid` on the event, or `error.fields` from a 422) into card state; first invalid card opens | `passengerForm.js` |
| 4 | Reducer: keep `passengerRequest.invalid`; on 422 from `submitPassengers` dispatch `ui/passenger_errors` instead of a generic `error` | `reducer.js`, `main.js` (`run()` must pass `error.fields` through) |
| 5 | CSS: `.field.is-invalid { border-color: var(--red) }`, `.pcard-tick { color: var(--green) }` | `styles/flights.css` |

### 2.6 Edge cases & tests

| Case | Expected |
|---|---|
| Duffel error without `source.pointer` | generic `ProviderError` as today (chat message), no card |
| Same passenger used in two sessions, fixed in one | the other session's next booking uses the fixed row (it's the same DB row) |
| User edits a valid field and makes it invalid | button disables again |
| 3 passengers, #2 invalid | #2 expanded, #1/#3 collapsed with ticks |
| Tests | `test_errors.py`: Pydantic loc → `FieldError`; `test_duffel.py`: pointer → `PassengerInvalid(index→id)`; `test_passengers_node.py`: `mode="fix"` request shape; `test_resume_passengers.py`: updates persisted then graph resumed |

---

## 3. Close a finished trip; new session per trip; keep history

### 3.1 UX

| When | What happens |
|---|---|
| `booking.lifecycle` becomes `confirmed` (paid **and** ticketed — `PaymentService._issue_ticket` set `CONFIRMED`) | Chat shows the confirmation, then becomes **read-only** (input replaced by "This trip is booked. [Start a new trip]"). Left pane keeps the trip view (ticket, ref). |
| User clicks **Start a new trip** (also on Home, and after a cancel) | `POST /api/sessions` → new thread id saved in `atlas.thread_id.<uid>` → reconnect SSE → empty state → Home (#1) |
| User reloads the old tab | snapshot has `closed: true` → read-only view, same button |
| Account → Bookings → a booking | "View conversation" opens the archived thread read-only |

Do **not** auto-jump to a new session the instant payment lands: the user wants to see the confirmation. Auto-start on
next visit instead: `openSession()` sees the saved thread is closed → creates a new one.

`TICKETING_FAILED` is **not** closed: it needs support/refund, keep the chat open.

### 3.2 Backend

| Change | Where |
|---|---|
| `chat_sessions.closed_at TIMESTAMPTZ NULL`, `closed_reason TEXT NULL` (`confirmed` / `cancelled` / `abandoned`), `title TEXT NULL` (e.g. "DEL → DXB · 2 Nov") | `app/db/models.py` `ChatSession` + Alembic migration |
| `Session.closed` → also in `session.state` so the snapshot carries it: `state["closed"] = {"at", "reason"}` | `app/api/sessions.py` (`empty_state`, `apply_event`) |
| `SessionStore.close(session, reason)` — sets fields, saves, publishes `session.closed` | `sessions.py` |
| Call it in `runner.publish_payment_change` when `booking.status == CONFIRMED` and `changed` | `app/api/runner.py` |
| Optional: close as `cancelled` after `finish_cancellation` — **recommended no**: leave it open so the user can search again in the same chat; only offer the button | — |
| Guard: every write route (`/messages`, `/search`, `/flight-selection`, `/approvals`, `/passenger-requests`, `/payments`) → `409 session_closed` if closed. Put it in `get_session(..., writable=True)` | `routes.py` |
| `/payments/{id}/sync` and the webhook stay allowed on closed sessions | `routes.py` |
| `GET /api/sessions?limit=20` → `[{thread_id, title, closed_at, closed_reason, booking_reference}]` for history | `routes.py` (or `account.py`) |
| New SSE event `session.closed {reason, at}` | `events.py`, `contract.js`, `api-contract.md` |

### 3.3 UI

| # | Step | File |
|---|---|---|
| 1 | Reducer: `session.closed` and `snapshot.closed` → `state.closed` | `reducer.js` |
| 2 | Chat input → read-only banner + "Start a new trip" when `state.closed` | `chatPane.js` |
| 3 | `actions.newTrip()`: `transport.newSession()` (= `api.createSession` + `safeSet(key)`), `store.dispatch({type:'ui/reset'})`, `transport.connect(newId)` | `main.js`, `transport.js`, `reducer.js` (`ui/reset` → `initialState`) |
| 4 | `openSession()`: if the saved thread's snapshot says closed, create a new one (or: server returns `closed` on a cheap `GET /api/sessions/{id}`) | `transport.js` |
| 5 | Account → booking detail: "View conversation" → open thread read-only (connect SSE, no input) | `src/ui/account/bookingDetailScreen.js` |

**Interaction with #1:** "Start a new trip" here and the Home form are the same flow: new session → Home. Implement
`newTrip()` once.

### 3.4 Edge cases & tests

| Case | Expected |
|---|---|
| Two tabs, one closes the session | other tab gets `session.closed` over SSE and goes read-only |
| Webhook arrives after close (duplicate PAID) | allowed; `apply_provider_status` dedupes; no reopen |
| Old thread id from before this change (no `closed_at`) | treated as open |
| Tests | close on CONFIRMED (`test_runner_payment.py`); 409 `session_closed` on each write route; snapshot contains `closed`; `GET /api/sessions` only returns own threads |

### 3.5 Future (not now): learn from past chats and searches with pgvector

| Topic | Plan |
|---|---|
| **When** | After #1–#4 ship and there are real users with ≥ ~20 trips each. Before that a plain SQL "most frequent route" beats any embedding. |
| **What to embed** | (a) each **search** as text: "DEL→DXB, Fri, 2 adults, economy, 14 days ahead"; (b) each **finished trip summary** (route, airline chosen vs cheapest, price paid, departure hour); (c) *not* raw chat text by default — it holds names/phones. |
| **Table** | `user_signals(id uuid, user_id uuid FK, kind text /*search|trip*/, source_id uuid, text text, embedding vector(1536), meta jsonb, created_at)`; index `USING hnsw (embedding vector_cosine_ops)`; btree on `(user_id, created_at)`. Always filter by `user_id` first. |
| **Use** | "Recommended for you": nearest past trips → preferred airline / time-of-day / cabin → re-rank `search_flights` results; or a tool `user_preferences()` for the agent. |
| **Privacy / retention** | opt-in toggle on Profile; no PII in `text` (strip names, emails, phones before embedding); delete rows on account deletion; 18-month retention job; embeddings stay in our Postgres, only the text goes to the embedding API. |
| **Cheaper first step** | `search_history` (from #4) + SQL aggregates already give "your usual route". |

---

## 4. Recent searches + cancel at any stage before payment completes

### 4.1 Recent searches (UX)

Home (#1) shows the **3 most recent distinct** searches: "DEL → DXB · Sun 2 Nov · 2 · Economy". One click = `POST /search`
with the same params. A past date is shown greyed with "pick a new date" (click fills the form instead of searching).

### 4.2 Recent searches (backend)

| Change | Where |
|---|---|
| Table `search_history(id uuid, user_id uuid FK, origin char(3), destination char(3), date date, passengers int, cabin text, thread_id text, created_at timestamptz)`; index `(user_id, created_at desc)` | `models.py` + migration |
| `SearchHistoryService.record(user_id, params, thread_id)` — called from `handle_search_flights` (so chat searches count too, not only the form) | `app/services/search_history.py`, `app/agent/handlers.py` |
| `GET /api/searches/recent?limit=3` → distinct on `(origin, destination, date, passengers, cabin)` newest first | `app/api/account.py` (it's plain REST, like the account endpoints) |
| Tests: dedupe, limit, user isolation | `tests/api/test_recent_searches.py` |

UI: `homeView.js` fetches on mount via `transport.api.recentSearches()` (REST, no SSE). Refetch after `search.completed`.

### 4.3 Cancel rules per stage

One user action: **"Cancel trip"** (left pane, visible whenever there is something to cancel; replaces today's
cancel button that only exists for held bookings, `routes.cancel_booking` → 409 otherwise).

| Stage (UI `journeyIndex` / DB) | What "cancel" does | Duffel | Cashfree | Confirm dialog? |
|---|---|---|---|---|
| Searching (busy) | stop the turn (`turn_manager` cancel / ignore result), clear results | — | — | no |
| Results / choosing | clear `flights`, `selection` → Home | — | — | no |
| Approval or passenger request pending | `supersede_pending()` with decision `cancelled` | — | — | no |
| **HELD** | existing flow: `request_cancellation` → approval → `finish_cancellation` → `BookingService.cancel_booking` | `cancel_order` (two-step cancellation) | — | yes (existing) |
| **AWAITING_PAYMENT, checkout not opened / created** | same as HELD **plus** terminate the open order | `cancel_order` | **terminate order** (`PATCH /pg/orders/{order_id}` `{"order_status":"TERMINATED"}`) | yes |
| **AWAITING_PAYMENT, user is in Cashfree checkout (payment `PENDING`)** | first **sync** the payment; if PAID → refuse (409 `payment_completed`, show confirmed); else terminate order, then cancel hold | after Cashfree terminate succeeds | terminate; if Cashfree says "already paid / cannot terminate" → treat as PAID | yes, with "If you already paid, we'll refund automatically" |
| PAID, ticketing in progress | not cancellable here (409) | — | — | — |
| CONFIRMED | not here: post-ticket cancellation = refund flow (Account, later) | — | — | — |

Order matters: **Cashfree first, Duffel second.** If we released the seat first and the payment then succeeded, we'd have
money and no seat.

### 4.4 Races with webhooks — rules

| Race | Rule | Implementation |
|---|---|---|
| Cancel and PAID webhook at the same time | one wins, decided **in Postgres** | `SELECT … FOR UPDATE` on the booking row in both `cancel_booking` and `apply_provider_status`; whoever locks first decides |
| PAID arrives **after** booking is CANCELLED | money must go back | in `PaymentService._transition`: if new status is PAID and `booking.status in (CANCELLED, EXPIRED)` → do **not** call `_issue_ticket`; set payment `REFUND_PENDING`, call `payment_provider.refund(order_id, amount)`; on refund webhook → `REFUNDED` |
| Today's ALLOWED map lets FAILED/EXPIRED → PAID ("late success still wins") | keep it, but the booking check above decides ticket vs refund | `payment.py` |
| Duffel hold already expired when PAID arrives | same as above → refund (today `_issue_ticket` would hit Duffel and set `TICKETING_FAILED`; refund is better) | `_issue_ticket` catches `OfferUnavailable`/order-expired → refund |
| Terminate call fails (network) | don't cancel the hold; return 503 `provider_unavailable`, retryable | `runner.finish_cancellation` |
| User double-clicks cancel | existing approval dedupe in `routes.decide` + `BookingService.cancel_booking` is idempotent | — |

DB changes: `PaymentStatus` gains `CANCELLED` (order terminated by us), `REFUND_PENDING`, `REFUNDED`; `ALLOWED` gains
`CREATED/PENDING → CANCELLED`, `CANCELLED → PAID` (late success, refund path), `PAID → REFUND_PENDING → REFUNDED`.
Provider interface (`app/providers/payment/base.py`): `terminate_order(order_id)`, `refund(order_id, amount, refund_id)`.

### 4.5 Reuse

| Existing piece | Reused for |
|---|---|
| `runner.request_cancellation` / `finish_cancellation` (app-level approval, no LLM) | HELD and AWAITING_PAYMENT cancel; extend `finish_cancellation` to terminate the Cashfree order first |
| `BookingService.cancel_booking` (idempotent, calls `flight_provider.cancel_order`) | unchanged, plus row lock |
| `PaymentService.sync_payment` | "check before cancel" while in checkout |
| `PaymentService.apply_provider_status` + `payment_events` dedupe | refund webhooks too |
| `runner.supersede_pending` | cancelling approvals / passenger requests |
| `routes.cancel_booking` | widen the 409 guard to all stages in the table; rename in contract to "cancel trip" |

### 4.6 Steps (backend, in order)

| # | Step | File |
|---|---|---|
| 1 | Migration: new `PaymentStatus` values; `ALLOWED` map update | `models.py`, `payment.py` |
| 2 | `CashfreeProvider.terminate_order`, `.refund` (+ fakes for tests) | `providers/payment/cashfree.py`, `base.py` |
| 3 | Row lock helper `BookingRepository.get_for_update` | `db/repositories/bookings.py` |
| 4 | `PaymentService.cancel_open_payment(booking)` → sync → terminate → `CANCELLED`, or raise `PaymentCompleted` | `payment.py` |
| 5 | `_transition`: PAID on a cancelled/expired booking → refund instead of ticket | `payment.py` |
| 6 | `finish_cancellation`: `cancel_open_payment` then `cancel_booking`; publish `payment.updated` with the real (cancelled) payment, not `None` | `runner.py` |
| 7 | `routes.cancel_booking`: allow pre-booking stages (clear search/approval without an approval dialog) | `routes.py` |
| 8 | Tests: each stage row in §4.3; PAID-after-cancel → refund; concurrent cancel + webhook (two tasks, one lock); terminate failure → 503 and hold intact | `tests/services/test_cancel_payment.py`, `tests/api/test_cancel_route.py` |

UI: one "Cancel trip" button in `tripView.js` / `flightsPane.js`; while the payment sheet is open, a "Cancel trip" link in
`paymentSheet.js` closes the sheet then calls `actions.cancelBooking()`; new copy for `payment.updated` status `cancelled` /
`refund_pending` / `refunded` in `tripView.js` (`STAGES`).

---

## 5. How the features interact

| Interaction | Rule |
|---|---|
| #1 Home ⇄ #3 new session | one action, `newTrip()`; Home is simply what an empty session looks like |
| #1 search ⇄ #4 recent | every search (form or chat) is recorded in `search_history`; recent list reruns via `/search` |
| #2 fix-passenger ⇄ #4 cancel | cancelling while a fix card is open = supersede the passenger request |
| #3 close ⇄ #4 cancel | a cancelled trip does **not** close the session (user may rebook); a confirmed one does |
| #3 close ⇄ late PAID refund (#4) | webhook/sync still work on closed sessions; refund status updates the archived thread |
| Journey bar (§0) | hides on empty/new sessions automatically; needs a "Cancelled" visual later (it no longer marks `is-cancelled`) |

## 6. Recommended build order

| Order | What | Why first |
|---|---|---|
| 1 | #3 close + `newTrip()` (backend `closed_at`, `session.closed`, 409 guard; UI read-only + button) | Every other feature assumes "one trip = one session" |
| 2 | #1 `POST /search` + Home form | Small, and it is where #3 lands the user |
| 3 | #4a recent searches | Tiny once `/search` exists |
| 4 | #2 field-level errors (422 `fields` first, then Duffel pointer → `PassengerInvalid`, then fix mode) | Self-contained, but touches the graph |
| 5 | #4b cancel at any stage + refund race | Highest risk (money); do it with tests first, in Cashfree sandbox |
| 6 | §3.5 pgvector | Only with real data |

## 7. Open questions

| Question | Default if nobody answers |
|---|---|
| Should a cancelled trip close the session too? | No (rebook in same chat) |
| Does Cashfree sandbox support `TERMINATED` for orders with an active payment attempt? | Verify in sandbox before step 4.6/4 |
| Refund automatically or queue for manual review? | Automatic, logged in `payment_events` |
| Home form: IATA codes only or airport autocomplete? | Codes now; autocomplete later via Duffel places API |
