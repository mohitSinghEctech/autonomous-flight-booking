# import asyncio

# from app.models import SearchFlights, Cabin
# from app.providers.flights.duffel import DuffelFlightProvider


# async def test_provider():
#     provider = DuffelFlightProvider()

#     request = SearchFlights(
#         origin="DEL",
#         destination="DXB",
#         date="2026-10-02",
#         passengers=2,
#         cabin=Cabin.ECONOMY,
#     )

#     flights = await provider.search_flights(request)

#     print("Flights returned:", len(flights))

#     for flight in flights[:3]:
#         print(flight)


# if __name__ == "__main__":
#     asyncio.run(test_provider())

import asyncio

from app.providers.flights.duffel import DuffelFlightProvider


async def main():
    provider = DuffelFlightProvider()

    flight = await provider.fetch_flight_details(
        "off_0000BAyeT0InBJxxjtkwIq"
    )

    print(flight)


if __name__ == "__main__":
    asyncio.run(main())