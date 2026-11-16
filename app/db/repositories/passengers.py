import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Passenger


# Fields a caller may set on a saved passenger (never id / user_id).
EDITABLE_FIELDS = frozenset(
    {"title", "given_name", "family_name", "gender", "born_on", "email", "phone_number"}
)


class PassengerRepository: 
    def __init__(self, session: AsyncSession):
        self.session = session
        
    async def get_passenger(
        self,
        passenger_id: uuid.UUID
    ) -> Passenger | None:
        result = await self.session.execute(
            select(Passenger)
            .where(Passenger.id == passenger_id)
        )
        
        return result.scalar_one_or_none()

    async def get_user_passenger(
        self,
        user_id: uuid.UUID,
        passenger_id: uuid.UUID,
    ) -> Passenger | None:
        """The passenger only if it belongs to this user. Ownership is part of the query."""
        result = await self.session.execute(
            select(Passenger)
            .where(Passenger.id == passenger_id, Passenger.user_id == user_id)
        )

        return result.scalar_one_or_none()
        
    async def get_passengers_by_user(
        self,
        user_id: uuid.UUID
    ) -> list[Passenger]:
        result = await self.session.execute(
            select(Passenger)
            .where(Passenger.user_id == user_id)
            .order_by(Passenger.given_name, Passenger.family_name, Passenger.id)
        )
        
        return list(result.scalars().all())

    async def get_passengers_by_ids(
        self,
        passenger_ids: list[uuid.UUID],
        user_id: uuid.UUID | None = None,
    ) -> list[Passenger]:
        """Passengers with these ids; with user_id, only that user's."""
        query = select(Passenger).where(Passenger.id.in_(passenger_ids))

        if user_id is not None:
            query = query.where(Passenger.user_id == user_id)

        result = await self.session.execute(query)

        return list(result.scalars().all())
        
    async def create_passenger(
        self,
        user_id: uuid.UUID,
        given_name: str,
        family_name: str,
        **details,
    ) -> Passenger:
        passenger = Passenger(
            user_id=user_id,
            given_name=given_name,
            family_name=family_name,
            **details,
        )
        
        self.session.add(passenger)
        
        await self.session.flush()
        
        return passenger

    async def update_passenger(
        self,
        passenger: Passenger,
        changes: dict,
    ) -> Passenger:
        unknown = set(changes) - EDITABLE_FIELDS
        if unknown:
            raise ValueError(f"Not editable: {', '.join(sorted(unknown))}")

        for field, value in changes.items():
            setattr(passenger, field, value)

        await self.session.flush()

        return passenger

    async def delete_passenger(
        self,
        passenger: Passenger,
    ) -> None:
        """Bookings that used this passenger keep their snapshot; the DB unlinks them."""
        await self.session.delete(passenger)

        await self.session.flush()
