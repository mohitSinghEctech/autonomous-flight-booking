import asyncio

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.db.models import User, Passenger
from app.db.session import SessionLocal


async def main():
    async with SessionLocal() as session:

        user = User(
            given_name="Rahul",
            family_name="Sharma",
        )

        passenger = Passenger(
            given_name="Priya",
            family_name="Sharma",
        )

        user.passengers.append(passenger)

        session.add(user)

        await session.commit()

        print(f"User: {user.id}")
        print(f"Passenger: {passenger.id}")
        
        result = await session.execute(
            select(User)
            .options(selectinload(User.passengers))
            .where(User.id == user.id)
        )

        loaded_user = result.scalar_one()

        print(f"User: {loaded_user.given_name} {loaded_user.family_name}")

        for passenger in loaded_user.passengers:
            print(
                f"Passenger: {passenger.given_name} {passenger.family_name}"
            )


if __name__ == "__main__":
    asyncio.run(main())