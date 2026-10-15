import os
import sys

from mcp import Client, StdioServerParameters

from app.core.settings import settings


class FlightMCPClient:
    def __init__(self):
        # The server runs as a child process that only gets the env we pass it,
        # so the Duffel token must be handed over explicitly.
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
