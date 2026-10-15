from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import SessionLocal

async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """One DB session per request, for routes that answer directly (not background turns)."""
    async with SessionLocal() as session:
        yield session