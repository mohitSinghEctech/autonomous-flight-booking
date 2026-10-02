from datetime import date

from app.models import Passenger


def get_saved_passengers() -> list[Passenger]:
    return [
        Passenger(
            id="passenger_001",
            title="mr",
            given_name="Mohit",
            family_name="Kumar Singh",
            gender="m",
            born_on=date(1993, 6, 24),
            email="mohit.singh.coder@gmail.com",
            phone_number="+919412143791",
        ),
        Passenger(
            id="passenger_002",
            title="ms",
            given_name="Akanksha",
            family_name="Trivedi",
            gender="f",
            born_on=date(1993, 2, 3),
            email="akankshatrivedi.3feb@gmail.com",
            phone_number="+917355008691",
        ),
    ]
    
from app.core.errors import PassengerNotFound


def get_passengers_by_ids(passenger_ids: list[str]) -> list[Passenger]:
    passengers = get_saved_passengers()

    passengers_by_id = {
        passenger.id: passenger
        for passenger in passengers
    }

    result = []

    for passenger_id in passenger_ids:
        passenger = passengers_by_id.get(passenger_id)

        if passenger is None:
            raise PassengerNotFound(
                f"Passenger not found: {passenger_id}"
            )

        result.append(passenger)

    return result