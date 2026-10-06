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
Full integration tests              ✅  62 tests, real uvicorn + Postgres + SSE

Docker                              ✅  alpine multi-stage 246 MB, non-root, healthcheck, compose: postgres → migrate → api
Observability                       ✅  JSON logs, request/thread/turn ids, LLM tokens + timings, token redaction
Production hardening                ✅  Firebase token verification, per-user sessions, restart-safe (Postgres
                                        checkpointer + chat_sessions), approval expiry, config fail-fast, DB health
Deployment                          ⏳  next — together

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
docker compose up --build -d     # postgres → migrate → api on :8000
uv run pytest -q                  # tests (need postgres up)
```

Docker lessons: MCP stdio passes only HOME/PATH to the server subprocess (pass secrets explicitly); Duffel test mode only holds reliably on Duffel Airways.

UI: `https://provenance.web.app/flight/?live=1` (or the agent-console emulator at `http://localhost:5055/flight/?emulate=1&live=1`).

## Next session: deployment

1. Pick the host (one container + managed Postgres): Cloud Run + Cloud SQL / Neon, or Render / Fly.
2. Secrets in the platform's secret store; `AUTH_MODE=firebase`, **no** `FIREBASE_AUTH_EMULATOR_HOST`.
3. Run `alembic upgrade head` as a release step, then start ONE instance (`PORT` is honoured).
4. `CASHFREE_WEBHOOK_URL` = the public URL; test the webhook end to end.
5. Point the UI at the API URL and redeploy agent-console.

Later: trim LLM context (~15k tokens per call), Langfuse tracing, CI.

## Docs

- `docs/api-layer.md`: how the API layer works, design decisions, tests, limits, interview answers
- `docs/api-fixes-2026-10-06.md`: the 500 and the 6 bugs found with it
- `agent-console/docs/api-contract.md`: the UI ↔ API contract (v1.1)
