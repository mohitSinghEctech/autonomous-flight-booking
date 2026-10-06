# Project 1 — AI Flight Booking: status

Updated 2026-10-06. This repo is the learning project for agentic AI, GenAI, RAG and backend engineering.

## Status board

```
FastAPI foundation                  ✅
Async Python                        ✅
Provider abstraction                ✅
Duffel integration                  ✅  (+ duration, order cancellation)
Domain models                       ✅
Booking lifecycle                   ✅  (+ cancelled, expired)
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
Full integration tests              ✅  45 tests, real uvicorn + Postgres + SSE

Docker                              ⏳  next — together
Observability                       ⏳
Production hardening                ⏳  (see api-layer.md §8)
Deployment                          ⏳  together

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
docker start flight_booking_postgres
uv run alembic upgrade head
uv run uvicorn app.main:app --reload --port 8000
uv run pytest -q
```

UI: `https://provenance.web.app/flight/?live=1` (or the agent-console emulator at `http://localhost:5055/flight/?emulate=1&live=1`).

## Next session

1. **Docker**: multi-stage image, non-root, health check, env vars (together).
2. **Observability**: request / thread / turn ids in structured logs, LLM / tool / DB latency.
3. **Hardening**: Postgres checkpointer, Firebase token verification, approval expiry.

## Docs

- `docs/api-layer.md`: how the API layer works, design decisions, tests, limits, interview answers
- `docs/api-fixes-2026-10-06.md`: the 500 and the 6 bugs found with it
- `agent-console/docs/api-contract.md`: the UI ↔ API contract (v1.1)
