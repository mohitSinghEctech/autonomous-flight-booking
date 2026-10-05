import json

import httpx

from app.agent.handlers import (
    ToolResult,
    handle_book_flight,
    handle_complete_payment,
    handle_create_payment,
    handle_get_saved_passengers,
    handle_search_flights,
)
from app.agent.state import AgentState
from app.core.errors import AppError


HANDLERS = {
    "search_flights": handle_search_flights,
    "get_saved_passengers": handle_get_saved_passengers,
    "book_flight": handle_book_flight,
    "create_payment": handle_create_payment,
    "complete_payment": handle_complete_payment,
}


async def execute_tool(tool_call: dict, state: dict) -> ToolResult:
    tool_name = tool_call["function"]["name"]

    handler = HANDLERS.get(tool_name)

    if handler is None:
        return ToolResult({"error": f"Unknown tool: {tool_name}"})

    # Expected failures go back to the LLM as data so it can react.
    try:
        return await handler(tool_call, state)
    except AppError as exc:
        return ToolResult({"error": str(exc)})
    except httpx.HTTPError as exc:
        return ToolResult({"error": f"Upstream provider error: {exc}"})


async def execute_tools(state: AgentState):
    """Tools node: run every tool call in the last LLM message."""

    tool_messages = []
    updates = {}

    for tool_call in state["messages"][-1]["tool_calls"]:
        print("Tool name:", tool_call["function"]["name"])

        # Later calls in the same turn see earlier calls' state changes
        result = await execute_tool(tool_call, {**state, **updates})
        updates.update(result.update)

        tool_messages.append({
            "role": "tool",
            "tool_call_id": tool_call["id"],
            "content": json.dumps(result.content),
        })

    return {"messages": tool_messages, **updates}
