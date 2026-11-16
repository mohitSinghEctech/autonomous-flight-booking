# AI Flight Booking (ATLAS backend)

An agent that searches, holds and pays for flights, and asks a human before anything irreversible.
FastAPI · LangGraph · LLM tool calling · MCP · PostgreSQL (SQLAlchemy async + Alembic) · Duffel · Cashfree · SSE.

**LLM proposes; application validates, authorizes and executes.**

## Run everything locally (Docker)

Needs `.env` (copy `.env.example`, fill the LLM / Duffel / Cashfree keys) and the `agent-console` repo next to this one.

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
uv run pytest -q                  # 135 integration tests (need postgres up)
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

Docs: [`docs/PROJECT_STATUS.md`](docs/PROJECT_STATUS.md) · [`docs/api-layer.md`](docs/api-layer.md) · [`docs/interview-guide.html`](docs/interview-guide.html) · [`docs/saved-passengers-plan.md`](docs/saved-passengers-plan.md) · contract: `agent-console/docs/api-contract.md`
