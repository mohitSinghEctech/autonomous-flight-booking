from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.core.settings import settings


def asyncpg_url(url: str) -> str:
    """
    Any standard Postgres URL -> the form SQLAlchemy + asyncpg accept.

    Hosted providers (Neon, RDS, Supabase) hand out libpq-style URLs:
    postgresql://…?sslmode=require&channel_binding=require. asyncpg rejects
    those query keys; it wants ssl=require instead.
    """
    parts = urlsplit(url)
    query = dict(parse_qsl(parts.query))
    sslmode = query.pop("sslmode", None)
    query.pop("channel_binding", None)
    if sslmode and sslmode != "disable" and "ssl" not in query:
        query["ssl"] = "require" if sslmode in ("require", "prefer", "allow") else sslmode
    scheme = "postgresql+asyncpg"
    return urlunsplit((scheme, parts.netloc, parts.path, urlencode(query), parts.fragment))


def libpq_url(url: str) -> str:
    """The same database as a plain libpq URL (psycopg: LangGraph's checkpointer)."""
    parts = urlsplit(url)
    query = dict(parse_qsl(parts.query))
    ssl = query.pop("ssl", None)
    if ssl and "sslmode" not in query:
        query["sslmode"] = ssl
    return urlunsplit(("postgresql", parts.netloc, parts.path, urlencode(query), parts.fragment))


# One place for the URL. Tests point DATABASE_URL at flight_booking_test.
DATABASE_URL = asyncpg_url(settings.database_url)

# Tests run each case on a fresh event loop; pooled asyncpg connections can't
# cross loops, so they ask for no pooling. pool_pre_ping: hosted Postgres
# (Neon) closes idle connections; check before reuse instead of failing a turn.
engine = create_async_engine(
    DATABASE_URL,
    **({"poolclass": NullPool} if settings.db_null_pool else {"pool_pre_ping": True}),
)

SessionLocal = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False
)
