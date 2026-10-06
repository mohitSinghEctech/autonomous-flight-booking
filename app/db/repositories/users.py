import uuid

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
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

    async def create_user(
        self,
        given_name: str,
        family_name: str,
    ) -> User:

        user = User(
            given_name=given_name,
            family_name=family_name,
        )

        self.session.add(user)

        await self.session.flush()

        return user

    async def get_or_create_by_firebase_uid(
        self,
        firebase_uid: str,
        given_name: str,
        family_name: str,
    ) -> User:
        """First sign-in creates the user. Two concurrent first requests: the unique
        constraint lets one insert win; the other reads it back."""

        result = await self.session.execute(
            select(User).where(User.firebase_uid == firebase_uid)
        )
        user = result.scalar_one_or_none()
        if user is not None:
            return user

        try:
            async with self.session.begin_nested():
                user = User(given_name=given_name, family_name=family_name, firebase_uid=firebase_uid)
                self.session.add(user)
                await self.session.flush()
            return user
        except IntegrityError:
            result = await self.session.execute(
                select(User).where(User.firebase_uid == firebase_uid)
            )
            return result.scalar_one()
