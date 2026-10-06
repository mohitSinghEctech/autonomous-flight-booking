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
from app.api import progress
from app.core.errors import AppError


HANDLERS = {
    "search_flights": handle_search_flights,
    "get_saved_passengers": handle_get_saved_passengers,
    "book_flight": handle_book_flight,
    "create_payment": handle_create_payment,
    "complete_payment": handle_complete_payment,
}

# How each tool appears in the browser: (step kind, title, status stage, status text)
TOOL_STEPS = {
    "search_flights": ("tool", "Searching flights", "searching", "Searching live flights…"),
    "get_saved_passengers": ("tool", "Loading your passengers", "loading_passengers", "Loading your saved passengers…"),
    "book_flight": ("tool", "Holding your seat", "booking", "Placing a hold with the airline…"),
    "create_payment": ("tool", "Creating your payment", "payment", "Opening secure checkout…"),
    "complete_payment": ("tool", "Checking your payment", "payment", "Checking your payment with Cashfree…"),
}


async def execute_tool(
    tool_call: dict,
    state: dict,
) -> ToolResult:

    tool_name = tool_call["function"]["name"]

    handler = HANDLERS.get(tool_name)

    if handler is None:
        return ToolResult({"error": f"Unknown tool: {tool_name}"})

    # Expected failures go back to the LLM as data so it can react.
    try:
        return await handler(tool_call, state)

    except AppError as exc:
        return ToolResult({"error": str(exc)}, summary=str(exc))

    except httpx.HTTPError as exc:
        return ToolResult({"error": f"Upstream provider error: {exc}"}, summary="Provider error")


async def execute_tools(state: AgentState):
    """Tools node: run every tool call in the last LLM message, reporting each as a step."""

    tool_messages = []
    updates = {}

    for tool_call in state["messages"][-1]["tool_calls"]:

        tool_name = tool_call["function"]["name"]
        kind, title, stage, status_text = TOOL_STEPS.get(
            tool_name, ("tool", tool_name, "thinking", "Working…")
        )

        step_id = await progress.start_step(
            kind, title, tool=tool_name, stage=stage, status_text=status_text,
        )

        # Later calls in the same turn see earlier calls' state changes
        result = await execute_tool(tool_call, {**state, **updates})
        updates.update(result.update)

        failed = isinstance(result.content, dict) and "error" in result.content

        for event, data in result.events:
            await progress.publish(event, data)

        await progress.finish_step(
            step_id,
            status="failed" if failed else "done",
            detail=result.summary,
        )

        tool_messages.append(
            {
                "role": "tool",
                "tool_call_id": tool_call["id"],
                "content": json.dumps(result.content, default=str),
            }
        )

    return {
        "messages": tool_messages,
        **updates,
    }
