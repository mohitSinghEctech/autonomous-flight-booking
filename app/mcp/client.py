from mcp import Client, StdioServerParameters

class FlightMCPClient:
    def __init__(self):
        self.server = StdioServerParameters(
            command="uv",
            args=["run", "mcp", "run", "app/mcp/server.py"],
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
                    "cabin": cabin
                },
            )
            
            return result.content[0].text