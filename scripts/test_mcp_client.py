import asyncio

from mcp import Client, StdioServerParameters


server = StdioServerParameters(
    command="uv",
    args=["run", "mcp", "run", "app/mcp/server.py"],
)


async def main():
    async with Client(server) as client:
        tools = await client.list_tools()

        print("Available tools:")
        for tool in tools.tools:
            print(f"- {tool.name}")

        result = await client.call_tool(
            "search_flights",
            {
                "origin": "DEL",
                "destination": "DXB",
                "date": "2026-10-10",
                "passengers": 2,
                "cabin": "economy",
            },
        )

        print("\nResult:")
        print(result)


if __name__ == "__main__":
    asyncio.run(main())