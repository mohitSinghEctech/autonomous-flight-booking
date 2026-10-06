# AI Flight Booking (ATLAS backend)

An agent that searches, holds and pays for flights — and asks a human before anything irreversible.
FastAPI · LangGraph · LLM tool calling · MCP · PostgreSQL (SQLAlchemy async + Alembic) · Duffel · Cashfree · SSE.

**LLM proposes; application validates, authorizes and executes.**

```bash
docker start flight_booking_postgres
uv run alembic upgrade head
uv run uvicorn app.main:app --reload --port 8000     # API
uv run pytest -q                                    # 45 integration tests
```

Web UI: `agent-console/public/flight` (live at provenance.web.app/flight, `?live=1` to use this API).

Docs: [`docs/PROJECT_STATUS.md`](docs/PROJECT_STATUS.md) · [`docs/api-layer.md`](docs/api-layer.md) · contract: `agent-console/docs/api-contract.md`
