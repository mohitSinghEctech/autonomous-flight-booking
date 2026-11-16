"""
The real flight MCP server (app/mcp/server.py) run as a stdio subprocess, with the
fake Duffel behind it. Used by tests/test_mcp.py to test the long-lived client
against a real process it can kill.

Test controls:
  - flight id "off_slow" answers after 30 s (timeouts)
  - tool "pid" returns this process id (one process shared? restarted?)
  - env MCP_STUB_FAIL_FLAG=<path>: while that file exists, the server crashes on launch
"""
import asyncio
import os
import sys
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))
os.environ.setdefault("FLIGHT_VENDOR_TOKEN", "test-token")

flag = os.environ.get("MCP_STUB_FAIL_FLAG")
if flag and Path(flag).exists():
    sys.exit("stub MCP server: failing on purpose")

from app.mcp import server  # noqa: E402
from tests.fakes import FakeFlightProvider  # noqa: E402

SLOW_FLIGHT = "off_slow"


class StubFlightProvider(FakeFlightProvider):
    async def fetch_flight_details(self, flight_id):
        if flight_id == SLOW_FLIGHT:
            await asyncio.sleep(30)
        return await super().fetch_flight_details(flight_id)


server.flight_provider = StubFlightProvider()


@server.mcp.tool()
async def pid() -> str:
    return str(os.getpid())


if __name__ == "__main__":
    server.mcp.run()
