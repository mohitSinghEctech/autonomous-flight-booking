from datetime import datetime, timedelta

from ..models import Airport, Cabin, Flight, SearchFlights, Stop, BookFlight
from ..core.errors import FlightNotFound, InsufficientSeats


AIRPORTS = {
    "DEL": Airport(
        airport_code="DEL",
        airport_name="Indira Gandhi International Airport",
    ),
    "DXB": Airport(
        airport_code="DXB",
        airport_name="Dubai International Airport",
    ),
    "BOM": Airport(
        airport_code="BOM",
        airport_name="Chhatrapati Shivaji Maharaj International Airport",
    ),
    "BLR": Airport(
        airport_code="BLR",
        airport_name="Kempegowda International Airport",
    ),
    "LHR": Airport(
        airport_code="LHR",
        airport_name="London Heathrow Airport",
    ),
    "SIN": Airport(
        airport_code="SIN",
        airport_name="Singapore Changi Airport",
    ),
}


ROUTES = [
    ("DEL", "DXB"),
    ("DEL", "LHR"),
    ("DEL", "SIN"),
    ("BOM", "DXB"),
    ("BOM", "SIN"),
    ("BLR", "DXB"),
    ("BLR", "LHR"),
    ("DXB", "DEL"),
    ("LHR", "DEL"),
    ("SIN", "DEL"),
]


def create_mock_flights() -> list[Flight]:
    flights = []

    today = datetime.now().replace(
        hour=0,
        minute=0,
        second=0,
        microsecond=0,
    )

    cabins = [
        Cabin.ECONOMY,
        Cabin.BUSINESS,
        Cabin.FIRST,
    ]

    for index in range(50):

        origin_code, destination_code = ROUTES[index % len(ROUTES)]

        departure = today + timedelta(
            days=(index % 7) + 1,
            hours=6 + (index % 12),
        )

        cabin = cabins[index % len(cabins)]

        available_seats = 5 + (index % 20)

        stops = []

        # Every third flight has one stop.
        if index % 3 == 0:

            if origin_code == "DEL":
                stop_code = "BOM"
            else:
                stop_code = "DEL"

            stop_arrival = departure + timedelta(hours=2)

            stop_departure = stop_arrival + timedelta(
                minutes=90
            )

            stops.append(
                Stop(
                    airport=AIRPORTS[stop_code],
                    arrival_datetime=stop_arrival,
                    departure_datetime=stop_departure,
                )
            )

            # Final arrival must happen after the stop departure.
            arrival = stop_departure + timedelta(
                hours=3,
                minutes=(index % 4) * 15,
            )

        else:
            # Direct flight.
            arrival = departure + timedelta(
                hours=3 + (index % 5),
                minutes=(index % 4) * 15,
            )

        flight = Flight(
            flight_id=f"AI{1000 + index}",
            flight_name=f"Adventure Air {1000 + index}",
            origin=AIRPORTS[origin_code],
            destination=AIRPORTS[destination_code],
            departure_datetime=departure,
            arrival_datetime=arrival,
            price=15000 + (index * 750),
            currency="INR",
            cabin=cabin,
            available_seats=available_seats,
            stops=stops,
        )

        flights.append(flight)

    return flights


MOCK_FLIGHTS = create_mock_flights()


def search_flights(request: SearchFlights) -> list[Flight]:
    """
    Simulates the external flight vendor API.

    The vendor is responsible for:
    - filtering by origin
    - filtering by destination
    - filtering by date
    - filtering by cabin
    - checking passenger availability
    """

    matching_flights = []

    for flight in MOCK_FLIGHTS:

        if flight.origin.airport_code != request.origin:
            continue

        if flight.destination.airport_code != request.destination:
            continue

        if flight.departure_datetime.date() != request.date:
            continue

        if flight.cabin != request.cabin:
            continue

        if flight.available_seats < request.passengers:
            continue

        matching_flights.append(flight)

    return matching_flights

def book_flight(request: BookFlight) -> dict:
    for flight in MOCK_FLIGHTS:
        if flight.flight_id != request.flight_id:
            continue

        if flight.available_seats < request.passengers:
            raise InsufficientSeats(f"Not enough seats available for flight {request.flight_id}")

        return {
            "booking_id": f"BK-{flight.flight_id}-001",
            "flight_id": flight.flight_id,
            "status": "confirmed",
            "passengers": request.passengers,
        }

    raise FlightNotFound(f"Flight {request.flight_id} not found.")

def get_flight(flight_id: str) -> Flight | None:
    for flight in MOCK_FLIGHTS:
        if flight.flight_id == flight_id:
            return flight

    return None