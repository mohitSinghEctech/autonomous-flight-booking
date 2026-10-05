import asyncio

from app.db.repositories.users import UserRepository
from app.db.session import SessionLocal


async def main():

    async with SessionLocal() as session:

        repository = UserRepository(session)

        user = await repository.create_user(
            given_name="Mohit",
            family_name="Singh",
        )

        print("Created:")
        print(user.id)
        print(user.given_name)
        print(user.family_name)

        fetched_user = await repository.get_user(user.id)

        print("\nFetched:")
        print(fetched_user.id)
        print(fetched_user.given_name)
        print(fetched_user.family_name)


if __name__ == "__main__":
    asyncio.run(main())