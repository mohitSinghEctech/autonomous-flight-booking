import sys
from pathlib import Path
from datetime import date
import json

sys.path.append(str(Path(__file__).resolve().parents[2]))

from mcp.server import MCPServer
from mcp.server.mcpserver.exceptions import ToolError

from app.models import Cabin, SearchFlights
from app.providers.flights.duffel import DuffelFlightProvider


mcp = MCPServer("Flight Booking Server")

flight_provider = DuffelFlightProvider()

@mcp.tool()
async def search_flights(
    origin: str,
    destination: str,
    date: date,
    passengers: int,
    cabin: Cabin,
) -> str:
    request = SearchFlights(
        origin=origin,
        destination=destination,
        date=date,
        passengers=passengers,
        cabin=cabin,
    )
    
    flights = await flight_provider.search_flights(request)
    
    return json.dumps(
        [flight.model_dump(mode="json")
        for flight in flights]
    )


@mcp.tool()
async def get_flight_details(flight_id: str) -> str:
    flight = await flight_provider.fetch_flight_details(flight_id)

    if flight is None:
        raise ToolError(f"Flight {flight_id} not found.")

    return flight.model_dump_json()


if __name__ == "__main__":
    mcp.run()