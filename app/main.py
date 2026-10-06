import logging
import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.errors import install_error_handlers
from app.api.events import CONTRACT_VERSION
from app.api.routes import router, webhooks


# The hosted UI (Firebase) and the local emulator. Exact origins, never "*":
# requests carry a bearer token once auth is wired.
DEFAULT_ORIGINS = [
    "https://provenance.web.app",
    "https://mks-agent-console.web.app",
    "http://localhost:5055",
    "http://127.0.0.1:5055",
]


def create_app() -> FastAPI:
    logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))

    app = FastAPI(
        title="ATLAS Flight Booking API",
        version=CONTRACT_VERSION,
    )

    extra = [o.strip() for o in os.getenv("CORS_ORIGINS", "").split(",") if o.strip()]

    app.add_middleware(
        CORSMiddleware,
        allow_origins=DEFAULT_ORIGINS + extra,
        allow_methods=["GET", "POST"],
        allow_headers=["Authorization", "Content-Type", "X-Contract-Version", "Last-Event-ID"],
    )

    install_error_handlers(app)

    app.include_router(router)
    app.include_router(webhooks)

    return app


app = create_app()
