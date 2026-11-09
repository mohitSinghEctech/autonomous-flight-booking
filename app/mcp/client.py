import os
import sys

from mcp import Client, StdioServerParameters

from app.core.settings import settings


class FlightMCPClient:
    def __init__(self):
        self.server = StdioServerParameters(
            command=sys.executable,
            args=["app/mcp/server.py"],
            env={
                "PATH": os.environ.get("PATH", ""),
                "FLIGHT_VENDOR_TOKEN": settings.flight_vendor_token,
            },
        )

    async def search_flights(
        self,
        origin: str,
        destination: str,
        date: str,
        passengers: int,
        cabin: str,
    ):
        async with Client(self.server) as client:
            result = await client.call_tool(
                "search_flights",
                {
                    "origin": origin,
                    "destination": destination,
                    "date": date,
                    "passengers": passengers,
                    "cabin": cabin,
                },
            )

            return result.content[0].text
