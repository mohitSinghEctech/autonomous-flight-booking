import asyncio

from app.models import SearchFlights, Cabin
from app.providers.flights.duffel import DuffelFlightProvider


async def test_provider():
    provider = DuffelFlightProvider()

    request = SearchFlights(
        origin="DEL",
        destination="DXB",
        date="2026-10-02",
        passengers=2,
        cabin=Cabin.ECONOMY,
    )

    flights = await provider.search_flights(request)

    print("Flights returned:", len(flights))

    for flight in flights[:3]:
        print(flight)
        
    offer = await provider._fetch_raw_offer(
        flights[0].provider_reference
    )

    print("\nRAW OFFER PASSENGERS:")
    for passenger in offer["passengers"]:
        print(passenger)


if __name__ == "__main__":
    asyncio.run(test_provider())