import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import User


class UserRepository:

    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_user(
        self,
        user_id: uuid.UUID,
    ) -> User | None:
        result = await self.session.execute(
            select(User).where(User.id == user_id)
        )

        return result.scalar_one_or_none()