from datetime import date

from app.models import Passenger


def get_saved_passengers() -> list[Passenger]:
    return [
        Passenger(
            id="passenger_001",
            title="mr",
            given_name="John",
            family_name="Doe",
            gender="m",
            born_on=date(1990, 1, 1),
            email="john@example.com",
            phone_number="+919999999999",
        ),
        Passenger(
            id="passenger_002",
            title="ms",
            given_name="Jane",
            family_name="Smith",
            gender="f",
            born_on=date(1992, 2, 2),
            email="jane@example.com",
            phone_number="+918888888888",
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