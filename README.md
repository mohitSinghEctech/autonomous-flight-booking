# AI Flight Booking (ATLAS backend)

An agent that searches, holds and pays for flights, and asks a human before anything irreversible.
FastAPI · LangGraph · LLM tool calling · MCP · PostgreSQL (SQLAlchemy async + Alembic) · Duffel · Cashfree · SSE.

**LLM proposes; application validates, authorizes and executes.**

## Run offline (no internet, no API keys)

`PROVIDER_MODE=offline` swaps the four internet services for local stand-ins in
`app/providers/offline.py`: a deterministic tool-calling LLM, a Duffel-like flight provider
(three offers for any route and date), a Cashfree-like payment provider (a sync after
creating a payment returns `paid`) and the MCP search. FastAPI, LangGraph, the services and
Postgres stay real. Sign-in must be `AUTH_MODE=demo` (Firebase needs the internet).

```bash
docker compose up -d postgres
uv run alembic upgrade head
PROVIDER_MODE=offline AUTH_MODE=demo uv run uvicorn app.main:app --port 8000
```

Open **http://localhost:8000/** (the UI in `web/`, served by the API at `/web/`) and type
`Find flights from BOM to LHR on 2027-01-10 for 1 passenger`. The payment step shows a local
demo checkout instead of Cashfree's.

Or with curl: `POST /api/sessions`, open `GET /api/sessions/{id}/stream`, send
`POST /api/sessions/{id}/messages` with `{"text": "Find flights from BOM to LHR on 2027-01-10 for 1 passenger", "client_id": "msg-0001"}`,
answer the passenger request and the approval, `POST /payments`, then `POST /payments/{id}/sync` → booking `confirmed`.
`tests/test_offline_mode.py` runs this flow end to end. The tests use the same offline classes (`tests/fakes.py`).

| Mode | LLM | Flights | Payments | Auth |
|---|---|---|---|---|
| `live` (default) | OpenAI | Duffel (test mode) | Cashfree sandbox | Firebase |
| `offline` | `OfflineLLM` | `OfflineFlightProvider` | `OfflinePaymentProvider` | demo user |

## Run everything locally (Docker, live mode)

Needs `.env` (copy `.env.example`, fill the LLM / Duffel / Cashfree keys) and the `agent-console` repo next to this one (its Firebase-gated copy of the UI). Without it, use the `web/` UI at http://localhost:8000/ with `AUTH_MODE=demo`.

```bash
docker compose up -d --build
```

| Service | URL | What |
|---|---|---|
| `web` | http://localhost:5055/index.html?emulate=1&next=/flight/ | ATLAS UI (served from `../agent-console/public`) |
| `web` | http://localhost:4055 | Firebase emulator UI (Auth users) |
| `web` | :9099 | Firebase Auth emulator |
| `api` | http://localhost:8000/api/health | FastAPI + LangGraph agent |
| `postgres` | :5432 | `flight_booking` database |
| `migrate` | one-shot | `alembic upgrade head` |
| `seed-user` | one-shot | creates the local test login in the Auth emulator |

Local test login (emulator only): `demo@atlas.test` / `atlas-demo-123` (set in `docker-compose.yml`).

```bash
docker compose logs -f api        # JSON logs
docker compose down               # stop (data kept in the postgres_data volume)
```

## Run without Docker

```bash
docker compose up -d postgres
uv run alembic upgrade head
uv run uvicorn app.main:app --reload --port 8000
uv run pytest -q                  # 141 integration tests, all offline (need postgres up)
```

## Deploy: database migrations

**Run `alembic upgrade head` before the new code starts serving.** The code and the schema
must match in both directions:

- new code on the old schema fails wherever a booking's travellers are read or written;
- old code on the new schema can't create bookings (it doesn't fill the new NOT NULL
  traveller columns), so keep the gap between migrating and rolling out the new code short.

`docker compose` already does this (`migrate` must finish before `api` starts). The
`Dockerfile` does **not** migrate on start, so on any other platform run it as a release step
with the same image and `DATABASE_URL`:

```bash
alembic upgrade head
alembic current                   # must print: f1b7c9d3e2a4 (head)
```

`alembic heads` shows the latest revision in the code; `alembic current` shows what the
database is at. Deploy only when they match.

Latest migration, `f1b7c9d3e2a4`: each booking keeps its own copy of its travellers
(backfilled for existing bookings), and deleting a saved passenger only unlinks it from past bookings.

**Rollback limit.** `alembic downgrade -1` (back to `4479a967ab31`) works only while no
saved passenger that was on a booking has been deleted. Once one has, the old schema can't
store that booking's traveller, so the downgrade stops with an error and changes nothing,
rather than deleting booking history. From then on, fix forward instead of rolling back.
A successful downgrade also drops the travellers' copies, so bookings show the
current saved-passenger details again.

## Web UI (`web/`)

Plain HTML, CSS and JavaScript modules, no build step and no framework. The API serves it at
`/web/` (same origin). Data flows one way: SSE events → `api/transport.js` → `state/reducer.js`
→ components; actions (message, approval, passengers, pay) are POSTs. Here it runs without
sign-in (`src/host.js`, the API in `AUTH_MODE=demo`).
