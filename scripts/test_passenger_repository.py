import asyncio

from app.db.repositories.users import UserRepository
from app.db.repositories.passengers import PassengerRepository
from app.db.session import SessionLocal


async def main():

    async with SessionLocal() as session:

        user_repository = UserRepository(session)
        passenger_repository = PassengerRepository(session)

        user = await user_repository.create_user(
            given_name="Mohit",
            family_name="Singh",
        )

        passenger = await passenger_repository.create_passenger(
            user_id=user.id,
            given_name="Mohit Kumar",
            family_name="Singh",
        )

        print("Created passenger:")
        print(passenger.id)
        print(passenger.given_name)
        print(passenger.family_name)

        passengers = await passenger_repository.get_passengers_by_user(
            user.id
        )

        print("\nUser passengers:")

        for passenger in passengers:
            print(
                passenger.id,
                passenger.given_name,
                passenger.family_name,
            )


if __name__ == "__main__":
    asyncio.run(main())