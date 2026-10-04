import asyncio

from app.mcp.client import FlightMCPClient


async def main():
    client = FlightMCPClient()

    result = await client.search_flights(
        origin="DEL",
        destination="DXB",
        date="2026-10-10",
        passengers=2,
        cabin="economy",
    )

    print(result)


if __name__ == "__main__":
    asyncio.run(main())