import os

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

# One place for the URL. Tests point DATABASE_URL at flight_booking_test.
DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql+asyncpg://flight_user:flight_password@localhost:5432/flight_booking",
)

# Tests run each case on a fresh event loop; pooled asyncpg connections can't
# cross loops, so they ask for no pooling.
engine = create_async_engine(
    DATABASE_URL,
    **({"poolclass": NullPool} if os.getenv("DB_NULL_POOL") else {}),
)

SessionLocal = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False
)
