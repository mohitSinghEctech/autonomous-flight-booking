import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db.models import Flight, FlightStop
from app.models import Flight as FlightModel


class FlightRepository:

    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_flight(
        self,
        flight_id: uuid.UUID,
    ) -> Flight | None:

        result = await self.session.execute(
            select(Flight)
            .options(selectinload(Flight.stops))
            .where(Flight.id == flight_id)
        )

        return result.scalar_one_or_none()

    async def get_by_provider_reference(
        self,
        provider: str,
        provider_reference: str,
    ) -> Flight | None:

        result = await self.session.execute(
            select(Flight)
            .options(selectinload(Flight.stops))
            .where(
                Flight.provider == provider,
                Flight.provider_reference == provider_reference,
            )
        )

        return result.scalar_one_or_none()

    async def create_flight(
        self,
        flight: FlightModel,
        provider: str,
    ) -> Flight:

        db_flight = Flight(
            provider=provider,
            provider_reference=(
                flight.provider_reference or flight.flight_id
            ),
            flight_number=flight.flight_id,
            flight_name=flight.flight_name,
            origin_airport_code=flight.origin.airport_code,
            origin_airport_name=flight.origin.airport_name,
            destination_airport_code=flight.destination.airport_code,
            destination_airport_name=flight.destination.airport_name,
            departure_datetime=flight.departure_datetime,
            arrival_datetime=flight.arrival_datetime,
            cabin=flight.cabin.value,
        )

        self.session.add(db_flight)

        await self.session.flush()

        for index, stop in enumerate(flight.stops, start=1):

            db_stop = FlightStop(
                flight_id=db_flight.id,
                stop_sequence=index,
                airport_code=stop.airport.airport_code,
                airport_name=stop.airport.airport_name,
                departure_time=stop.departure_datetime,
                arrival_time=stop.arrival_datetime,
            )

            self.session.add(db_stop)

        return db_flight