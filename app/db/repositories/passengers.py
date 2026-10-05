import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Passenger

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
        
    async def get_passengers_by_user(
        self,
        user_id: uuid.UUID
    ) -> list[Passenger]:
        result = await self.session.execute(
            select(Passenger)
            .where(Passenger.user_id == user_id)
        )
        
        return list(result.scalars().all())

    async def get_passengers_by_ids(
        self,
        passenger_ids: list[uuid.UUID]
    ) -> list[Passenger]:
        result = await self.session.execute(
            select(Passenger)
            .where(Passenger.id.in_(passenger_ids))
        )

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