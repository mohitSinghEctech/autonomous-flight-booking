# API layer — how the backend talks to the web UI

Contract: `agent-console/docs/api-contract.md` (v1.1). This document explains **how this repo implements it**.

```
Browser ──POST──► routes.py ──acquire turn──► background task ──► runner.py ──► LangGraph
   ▲                                                                   │           │
   │                                                              progress.py ◄────┘ (nodes, tools)
   │                                                                   │
   └────────── SSE ◄── routes.stream ◄── event_bus.py ──► sessions.py (projection = snapshot)
```

Rule that holds everywhere: **the LLM proposes; the application validates, authorizes and executes.**

---

## 1. Files

| File | One job |
|---|---|
| `app/main.py` | app factory: CORS, error handlers, routers |
| `app/api/routes.py` | HTTP surface. Thin: validate → check state → take the turn lock → start work → `202` |
| `app/api/turns.py` | `TurnManager`: one unit of work per conversation (lock taken **in the request**, not in the task) |
| `app/api/runner.py` | every unit of background work is a **turn**: graph runs, approvals, payments, cancellation, webhook application |
| `app/api/progress.py` | how any layer reports to the browser (`start_step`, `set_status`, `publish_message`…). A `ContextVar` carries the current turn |
| `app/api/event_bus.py` | per-thread pub/sub: ids, history, fan-out to open streams, feeds the projection |
| `app/api/sessions.py` | per-thread memory: the **projection** (what `session.snapshot` sends), `client_id`s seen, resolved approvals, order → thread map |
| `app/api/events.py` | the contract as code: `SSEEvent` + Pydantic models for every event and request body |
| `app/api/views.py` | DB rows / domain models → contract shapes (provider ids, local flight times, checkout block) |
| `app/api/errors.py` | one error shape `{"error": {code, message, retryable}}` + exception → code mapping |
| `app/agent/passengers.py` | the passenger-required interrupt (v1.1) |
| `alembic/versions/b41c…`, `c7d3…` | `CANCELLED`/`EXPIRED` statuses; the missing `payments.payment_session_id` column |
| `tests/` | integration tests: real uvicorn + Postgres + SSE; fakes only for LLM / Duffel / Cashfree |

---

## 2. A turn

```
turn.started → status{busy} → step… message… flights.results… → [approval.required] → turn.completed{outcome} → status{idle | awaiting_approval}
```

`runner.turn()` is an async context manager. Whatever happens inside it:

- an exception never reaches the HTTP layer. It becomes: running steps → `failed`, an `error{code, message}` safe to show, and `turn.completed{outcome:"failed"}`;
- the final `status` is always sent, and the lock is always released (`routes.start_turn`'s `finally`).

The **ContextVar** is why nodes don't need `thread_id`. The runner sets the turn, LangGraph runs the nodes in tasks that copy the context, and `progress.start_step(...)` knows where to publish. Outside the API (`python -m app.graph`) there is no turn, and progress calls do nothing.

---

## 3. Human in the loop

| Situation | Who pauses | Event | Answer endpoint | Resume |
|---|---|---|---|---|
| LLM wants `book_flight` | `approval_node` → `interrupt()` | `approval.required{kind: book\|change}` | `POST /approvals/{id}` | `Command(resume="approved"\|"rejected")` |
| not enough / incomplete passengers | `passengers_node` → `interrupt()` | `passenger.required` | `POST /passenger-requests/{id}` | `Command(resume={decision, passengers})` |
| user presses **Cancel booking** | runner (app-level, no LLM) | `approval.required{kind: cancel}` | `POST /approvals/{id}` | runner cancels at Duffel |

Details that matter:

- **The ids are stable** (`ap_<tool_call_id>`, `pr_<tool_call_id>`). LangGraph **re-runs the paused node from the top** on resume, so a random id would change.
- **The runner publishes `approval.required`**, from `result["__interrupt__"]`. Publishing inside the node would send it twice.
- **Waiting ≠ busy.** A new message while something is pending → `supersede_pending()` resumes the graph with `"superseded"`. The node closes the tool calls and adds one assistant line, and the graph routes to `END`.
- **Change flow:** `handle_book_flight` sees an active booking in state → `BookingService.cancel_booking()` (Duffel order cancellation) → then books the new flight.

---

## 4. Payments

```
[Pay] → POST /payments → runner.start_payment → PaymentService.create_payment
                                                ├ open payment exists → reuse it (idempotent)
                                                ├ failed before → new Cashfree order "<booking>-<suffix>" (same row: one payment per booking)
                                                └ booking → AWAITING_PAYMENT, commit
      ◄ payment.updated{created, checkout{payment_session_id}} → the UI mounts Cashfree's checkout

Cashfree ── webhook ─► POST /api/webhooks/cashfree ─┐
UI (no update in 8 s) ─► POST /payments/{id}/sync ──┤
                                                    ▼
                      PaymentService.apply_provider_status / _transition   ← ONE place
                         ├ dedupe: (provider, provider_event_id) unique in payment_events
                         ├ legal moves only (PAID is terminal; a late success beats FAILED)
                         └ PAID → booking CONFIRMED (same transaction)
      ◄ payment.updated{paid} + booking.updated{confirmed} + "[app] Payment received" in the agent's history
```

- **The webhook signature** is checked on the **raw body**: `base64(HMAC-SHA256(secret, timestamp + body))`. Duplicates return `200 {duplicate: true}`, because Cashfree retries anything else.
- **Locally,** Cashfree can't reach `localhost`. Set `CASHFREE_WEBHOOK_URL` to a tunnel URL, or rely on `/sync`.
- **Order → thread:** `session_store.order_threads` (in memory) tells the webhook whose stream to update.

---

## 5. Keeping the agent honest

Things that change **outside** the chat (payment button, webhook, cancel) call `runner.sync_agent_state()`:

1. `graph.aupdate_state()` sets `booking` / `payment` / `db_booking_id`;
2. an **`[app] …` assistant line** is appended to the history.

Without (2), the real model trusted its own earlier "your seat is on hold" over the state flag, and refused to book again after a cancellation. That was found in the live test, and the regression is now in `test_cancel_booking_needs_approval`. The system prompt says `[app]` lines override earlier messages.

---

## 6. Snapshot and reconnect

`sessions.apply_event()` applies every published event to a dict, using **the same rules as the browser's reducer**. The stream route subscribes first, then sends that dict as `session.snapshot` with `id = last event id`, then only live events with a higher id. Results:

- a reload or reconnect redraws exactly;
- no duplicate bubbles (the UI skips ids it already has);
- no replay gaps.

---

## 7. Tests

```bash
docker start flight_booking_postgres
uv run pytest -q          # 62 tests, ~36 s
```

| File | Covers |
|---|---|
| `test_search_and_approval.py` | snapshot first, event order, approval shape, steps, `client_id` as message id |
| `test_booking.py` | approve / reject / double-click / early approval / supersede / board selection / change / cancel / 409 busy / `client_id` dedupe |
| `test_payments.py` | checkout, idempotent create, sync, webhook confirm + duplicate + bad signature, PAID never downgraded, retry after failure, 409 on paid |
| `test_passengers.py` | interrupt, save + continue to approval, 422 bad phone / wrong count, cancel the form |
| `test_stream.py` | increasing ids, reconnect snapshot, heartbeat, error shapes, CORS |
| `test_units.py` | SSE framing, Duffel durations, Cashfree status + signature + webhook parsing, projection |
| `test_auth.py` | real RS256 tokens (own test key), bad signature / audience / expiry / kid, user created once, 404 on someone else's thread, emulator tokens, redaction, request id |
| `test_persistence.py` | restart with a pending approval → approve → booked (real Postgres checkpointer), dedupe after restart, expired approval books nothing |

How they work: `conftest.py` creates and migrates `flight_booking_test`, starts the real app on a free port, and swaps `all_providers.flight_provider` / `payment_provider`, the MCP client and the OpenAI client for fakes (`tests/fakes.py`). `FakeLLM` is rule-based, so flows are deterministic. Services look providers up **at call time** (`all_providers.x`), which is what makes this swap possible without a DI framework.

The suite ran green 3 times in a row. It was also checked live (`?live=1`) with the real LLM, Duffel test mode and the Cashfree sandbox: search → approve → hold → real Duffel cancel → re-book → real Cashfree checkout inside the sheet → reload restores everything.

---

## 8. Production readiness (added 2026-10-06)

### Auth — `app/api/auth.py`
- The browser sends its Firebase ID token (`Authorization: Bearer`, or `?access_token=` on the stream).
- We verify it **without firebase-admin**: RS256 signature against Google's published certs (cached for their `max-age`), `aud` = project id, `iss` = `securetoken.google.com/<project>`, `exp`, `sub`.
- The uid maps to `users.firebase_uid`. A user is created on first sign-in, and the unique constraint settles the race between two first requests.
- **Every session has an owner.** Someone else's `thread_id` returns **404, not 403**, so ids can't be probed.
- `AUTH_MODE=demo` turns auth off (tests, curl). `FIREBASE_AUTH_EMULATOR_HOST` accepts the emulator's unsigned tokens. Both print a startup warning.

### Restarts — conversations and the agent survive
| What | Where |
|---|---|
| Agent memory (messages, state, **a paused interrupt**) | LangGraph `AsyncPostgresSaver`, opened in the app lifespan |
| UI projection + bookkeeping (client_ids, resolved approvals, turn counter, **last event id**) | `chat_sessions` (JSONB), saved after every turn and payment update (`save_soon`: never delays the lock) |
| Order → conversation for webhooks | memory, falling back to a JSONB query on `chat_sessions.state.payment.payment_id` |

Event ids continue from the saved `last_event_id`. If they restarted at 1, the browser (which skips ids it has seen) would silently drop new events.

### Approval expiry
The approval carries the offer's `expires_at`. Approving after it → decision `expired` → nothing is booked, and the agent is told to search again.

### Observability — `app/core/logging.py`
- One JSON object per line. `request_id` (middleware, echoed as `X-Request-ID`), `thread_id` and `turn_id` (ContextVars) are attached automatically.
- `llm call`: model, duration, input/output tokens, tool calls.
- `tool call`: tool, duration, ok, error.
- `turn finished`: origin, outcome, duration, LLM calls, tokens.
- The access log is ours: path without the query string. `redact()` masks `access_token=`, `Bearer …` and any JWT anywhere.

### Still single-process (by design for now)
The turn lock and the live SSE fan-out are in memory, so run **one** API instance (one uvicorn worker). Scaling out needs Redis / Postgres `LISTEN/NOTIFY` for the fan-out and a shared lock.

| Remaining limit | Fix when needed |
|---|---|
| one instance only | shared fan-out + lock |
| Duffel hold succeeds but the DB write fails → orphan hold | outbox / compensating cancel |
| ~15k input tokens per LLM call (50 flights in history) | trim tool results in history; send the model a summary, not every offer |

---

## 9. Interview answers this layer gives you

- **Why 202 + SSE instead of one long POST?** Agent turns take 10–40 s with many intermediate states. 202 frees the request, SSE streams progress, and reconnect is built in.
- **How do you stop a double booking?** The approval gate, an idempotent answer (same `approval_id` + decision → 202, nothing reruns), the turn lock, and `client_id` dedupe.
- **How is a webhook made idempotent?** A unique `(provider, provider_event_id)` plus a state machine that only allows legal moves. A duplicate → 200, no change.
- **Why does the snapshot exist?** Event history is bounded, and a fresh tab needs the whole state. The projection is the same reducer the UI runs.
- **What breaks with 2 API instances?** In-memory lock, bus and sessions. The webhook may land on the instance without the stream. Move them to shared storage.
