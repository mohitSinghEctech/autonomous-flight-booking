import sys
from pathlib import Path
from datetime import date
import json

sys.path.append(str(Path(__file__).resolve().parents[2]))

from mcp.server import MCPServer

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
    

if __name__ == "__main__":
    mcp.run()