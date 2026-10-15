import logging
import time
import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware

from app.agent import graph as agent_graph
from app.api.errors import install_error_handlers
from app.api.events import CONTRACT_VERSION
from app.api.routes import router, webhooks
from app.api.account import account
from app.api.sessions import session_store
from app.core.logging import log_fields, request_id_var, setup_logging
from app.core.settings import settings
from app.db.session import DATABASE_URL


# The hosted UI (Firebase) and the local emulator. Exact origins, never "*":
# requests carry a bearer token.
DEFAULT_ORIGINS = [
    "https://provenance.web.app",
    "https://mks-agent-console.web.app",
    "http://localhost:5055",
    "http://127.0.0.1:5055",
]

# Settings the API cannot run without (environment variable names)
REQUIRED = ["llm_api_key", "llm_model", "flight_vendor_token", "cashfree_app_id", "cashfree_api_key"]

logger = logging.getLogger("app")
access = logging.getLogger("app.http")


def check_config() -> None:
    """Fail at startup, with a clear message, instead of on the first user request."""

    missing = [name.upper() for name in REQUIRED if not getattr(settings, name)]
    if missing:
        raise RuntimeError(f"Missing required environment variables: {', '.join(missing)}")

    # AUTH_MODE is already checked by Settings (only "firebase" or "demo" are accepted)
    if settings.auth_mode == "demo":
        logger.warning("AUTH_MODE=demo: no sign-in required, every caller is the demo user. Never use this in production.")
    if settings.firebase_auth_emulator_host:
        logger.warning("FIREBASE_AUTH_EMULATOR_HOST is set: token signatures are NOT checked. Local development only.")


@asynccontextmanager
async def lifespan(app: FastAPI):
    check_config()

    async with agent_graph.postgres_checkpointer(DATABASE_URL):
        log_fields(logger, "api started", contract_version=CONTRACT_VERSION, auth_mode=settings.auth_mode)
        yield
        await session_store.flush()

    logger.info("api stopped")


def create_app() -> FastAPI:
    setup_logging(settings.log_level)

    app = FastAPI(
        title="ATLAS Flight Booking API",
        version=CONTRACT_VERSION,
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=DEFAULT_ORIGINS + settings.cors_origin_list,
        allow_methods=["GET", "POST"],
        allow_headers=["Authorization", "Content-Type", "X-Contract-Version", "Last-Event-ID", "X-Request-ID"],
        expose_headers=["X-Request-ID"],
    )

    @app.middleware("http")
    async def request_context(request: Request, call_next):
        """A request id on every log line of this request (and back to the caller),
        plus one access-log line. The path is logged WITHOUT the query string:
        that's where the SSE token travels."""

        request_id = request.headers.get("x-request-id") or uuid.uuid4().hex[:16]
        token = request_id_var.set(request_id)
        started = time.monotonic()
        status = 500

        try:
            response = await call_next(request)
            status = response.status_code
            response.headers["X-Request-ID"] = request_id
            return response
        finally:
            if request.url.path != "/api/health":        # the health check runs every 30 s
                log_fields(
                    access, f"{request.method} {request.url.path} {status}",
                    method=request.method,
                    path=request.url.path,
                    status=status,
                    duration_ms=round((time.monotonic() - started) * 1000),
                    client=request.client.host if request.client else None,
                )
            request_id_var.reset(token)

    install_error_handlers(app)

    app.include_router(router)
    app.include_router(account)
    app.include_router(webhooks)

    return app


app = create_app()
