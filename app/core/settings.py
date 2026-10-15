"""
All configuration in one place.

Values come from environment variables; locally they can also come from `.env`.
Read once at import, then used everywhere as `settings.<name>`:

    from app.core.settings import settings
    settings.llm_model

Secrets default to "" so tools that only need the database (alembic, tests)
can import the app. The API checks the required ones at startup (main.check_config).
"""
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # ---- app ----
    log_level: str = "INFO"
    cors_origins: str = ""                  # extra allowed origins, comma separated

    # ---- database ----
    database_url: str = "postgresql+asyncpg://flight_user:flight_password@localhost:5432/flight_booking"
    db_null_pool: bool = False              # tests: no pooling (each test has its own event loop)

    # ---- LLM ----
    llm_api_key: str = ""
    llm_model: str = ""

    # ---- flights (Duffel) ----
    flight_vendor_token: str = ""

    # ---- payments (Cashfree) ----
    cashfree_app_id: str = ""
    cashfree_api_key: str = ""
    cashfree_env: Literal["sandbox", "production"] = "sandbox"
    cashfree_webhook_url: str | None = None
    # Sandbox only: charge test orders in this currency (Indian test cards can't pay GBP).
    cashfree_test_currency: str | None = None

    # ---- auth (Firebase) ----
    auth_mode: Literal["firebase", "demo"] = "firebase"
    firebase_project_id: str = "mks-agent-console"
    firebase_auth_emulator_host: str | None = None
    demo_user_id: str = "eeb6ff6a-c66f-4874-a5aa-7c773962e14e"

    @property
    def cors_origin_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]


settings = Settings()
