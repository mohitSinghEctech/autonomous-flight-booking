# Project 1 — AI Flight Booking: status

Updated 2026-11-09. This repo is the learning project for agentic AI, GenAI, RAG and backend engineering.

## Status board

```
FastAPI foundation                  ✅
Async Python                        ✅
Provider abstraction                ✅
Duffel integration                  ✅  (+ duration, order cancellation)
Domain models                       ✅
Booking lifecycle                   ✅  (+ cancelled, expired, ticketing_failed)
LLM tool calling                    ✅
LangGraph                           ✅
State/routing                       ✅
JSON-safe state                     ✅
Human approval                      ✅  book / change / cancel, over the web
MCP                                 ✅
PostgreSQL                          ✅
SQLAlchemy                          ✅
Alembic                             ✅  (+ 2 migrations; `alembic check` clean)
Repositories                        ✅
Service layer                       ✅
Payment provider                    ✅
Payment service                     ✅
Payment idempotency                 ✅  tested
Paid → ticketed (Duffel pay order)  ✅  ticketing_failed when Duffel refuses after payment

SSE transport                       ✅
SSE heartbeat                       ✅
SSE event IDs                       ✅
SSE event history                   ✅
SSE snapshot (full-state projection)✅
Reconnect                           ✅  (reload / network drop)
Background turns                    ✅
Concurrent turn rejection           ✅

LangGraph → SSE integration         ✅
Flight SSE events                   ✅
Approval SSE workflow               ✅
Booking SSE events                  ✅
Payment SSE events                  ✅

Web contract completion             ✅  contract v1.1, UI works live (?live=1)
Payment webhook idempotency         ✅  signed + (provider, event_id) unique + state machine
Passenger-required workflow         ✅  interrupt → form → Postgres → resume
Full integration tests              ✅  71 tests, real uvicorn + Postgres + SSE (fakes for LLM/Duffel/Cashfree)
Account API: bookings list + detail ✅  GET /api/bookings, GET /api/bookings/{id}
Account API: cancel, passengers     ❌  planned (docs/account-api-plan.md)
Booking-flow UX (contract v1.3)     ❌  planned (docs/booking-flow-ux-plan.md)

Docker                              ✅  alpine multi-stage, non-root, healthcheck; compose runs the whole
                                        stack: postgres → migrate → api + web (UI + Auth emulator) + seed-user
Observability                       ✅  JSON logs, request/thread/turn ids, LLM tokens + timings, token redaction
Production hardening                ✅  Firebase token verification, per-user sessions, restart-safe (Postgres
                                        checkpointer + chat_sessions), approval expiry, config fail-fast, DB health
Deployment                          ❌  not started

Project 2 RAG                       ⏸ DEFERRED
```

## What "done" was checked against

| Check | How |
|---|---|
| search → approval → hold → pay → confirmed | `tests/test_booking.py`, `tests/test_payments.py` |
| double click / retry / busy | approval idempotency, `client_id` dedupe, 409 `turn_in_progress` |
| webhook twice / forged | `test_webhook_confirms_and_is_idempotent`, `test_webhook_with_a_bad_signature_is_401` |
| reconnect | `test_reconnect_gets_a_full_snapshot` + a live page reload |
| real providers | live run: Duffel test hold + cancel, Cashfree sandbox checkout rendered in the UI |

## Run

```bash
docker compose up -d --build      # whole stack, see README for URLs
uv run pytest -q                  # tests (need postgres up)
```

UI locally: `http://localhost:5055/index.html?emulate=1&next=/flight/` (login `demo@atlas.test` / `atlas-demo-123`, emulator only).
Live UI: `https://provenance.web.app/flight/` (talks to `http://localhost:8000/api` by default; `?api=` for another API).

Notes:
- MCP stdio passes only HOME/PATH to the server subprocess, so secrets are passed explicitly.
- Duffel test mode only holds reliably on Duffel Airways (ZZ); other carriers often answer `offer_no_longer_available`.
- Cashfree sandbox charges in `CASHFREE_TEST_CURRENCY` (INR) when set; never in production.
- The mock flight/payment/passenger providers were removed; tests use `tests/fakes.py`.

## Not done yet

| Area | State |
|---|---|
| Account API: cancel from account page, passenger list/add/delete, pagination cursor | planned, `docs/account-api-plan.md` |
| Booking-flow UX: home search form, inline passenger errors, close trip, recent searches | planned, `docs/booking-flow-ux-plan.md` |
| Deployment (host, managed Postgres, secrets, public webhook URL) | not started |
| LLM context trim (~15k input tokens per call), tracing, CI | not started |

## Docs

- `docs/api-layer.md`: how the API layer works, design decisions, tests, limits
- `docs/interview-guide.html`: the whole project explained for interviews
- `docs/api-fixes-2026-10-06.md`: the 500 and the 6 bugs found with it (history)
- `docs/account-api-plan.md`, `docs/booking-flow-ux-plan.md`: planned work
- `agent-console/docs/api-contract.md`: the UI ↔ API contract (v1.1)
