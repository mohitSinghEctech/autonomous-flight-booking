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
uv run pytest -q                  # 71 integration tests (need postgres up)
```

Docs: [`docs/PROJECT_STATUS.md`](docs/PROJECT_STATUS.md) · [`docs/api-layer.md`](docs/api-layer.md) · [`docs/interview-guide.html`](docs/interview-guide.html) · contract: `agent-console/docs/api-contract.md`
