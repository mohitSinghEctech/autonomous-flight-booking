import asyncio
from datetime import date

from app.models import BookFlight, Cabin, SearchFlights
from app.providers.flights.duffel import DuffelFlightProvider
from app.providers.user.passengers_mock import get_saved_passengers


async def main():
    provider = DuffelFlightProvider()
    
    request = SearchFlights(
        origin="DEL",
        destination="DXB",
        date=date(2026, 10, 2),
        passengers=2,
        cabin=Cabin.ECONOMY,
    )

    # Search for flights
    flights = await provider.search_flights(request)

    flight = flights[0]

    print("\nSelected flight:")
    print(flight)

    # Load saved passengers
    passengers = get_saved_passengers()

    print("\nPassengers:")
    for passenger in passengers:
        print(
            passenger.id,
            passenger.given_name,
            passenger.family_name,
        )

    # Create booking request
    request = BookFlight(
        flight_id=flight.flight_id,
        passenger_ids=[
            "passenger_001",
            "passenger_002",
        ],
    )

    print("\nCreating hold order...")

    order = await provider.book_flight(
        request,
        flight,
        passengers,
    )

    print("\nOrder created:")
    print(order)


if __name__ == "__main__":
    asyncio.run(main())