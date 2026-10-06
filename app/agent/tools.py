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
from langchain_core.runnables import RunnableConfig

from app.agent.state import AgentState
from app.api.event_bus import event_bus
from app.api.events import SSEEvent
from app.core.errors import AppError


HANDLERS = {
    "search_flights": handle_search_flights,
    "get_saved_passengers": handle_get_saved_passengers,
    "book_flight": handle_book_flight,
    "create_payment": handle_create_payment,
    "complete_payment": handle_complete_payment,
}


async def execute_tool(
    tool_call: dict,
    state: dict,
) -> ToolResult:

    tool_name = tool_call["function"]["name"]

    handler = HANDLERS.get(tool_name)

    if handler is None:
        return ToolResult(
            {
                "error": f"Unknown tool: {tool_name}",
            }
        )

    try:
        return await handler(
            tool_call,
            state,
        )

    except AppError as exc:
        return ToolResult(
            {
                "error": str(exc),
            }
        )

    except httpx.HTTPError as exc:
        return ToolResult(
            {
                "error": f"Upstream provider error: {exc}",
            }
        )


async def publish_tool_event(
    thread_id: str,
    tool_name: str,
    result: ToolResult,
) -> None:

    if tool_name == "search_flights":

        await event_bus.publish(
            thread_id,
            SSEEvent(
                event="flights.results",
                data={
                    "flights": result.content,
                },
            ),
        )

        return

    if tool_name == "book_flight":

        await event_bus.publish(
            thread_id,
            SSEEvent(
                event="booking.updated",
                data={
                    "booking": result.update.get("booking"),
                },
            ),
        )

        return

    if tool_name in {
        "create_payment",
        "complete_payment",
    }:

        payment = result.update.get("payment")
        booking = result.update.get("booking")

        await event_bus.publish(
            thread_id,
            SSEEvent(
                event="payment.updated",
                data={
                    "payment": payment,
                    "booking": booking,
                },
            ),
        )


async def execute_tools(state: AgentState, config: RunnableConfig):

    tool_messages = []
    updates = {}

    # thread_id comes from config (state only keeps AgentState's keys).
    thread_id = config["configurable"]["thread_id"]

    for tool_call in state["messages"][-1]["tool_calls"]:

        tool_name = tool_call["function"]["name"]

        print("Tool name:", tool_name)

        result = await execute_tool(
            tool_call,
            {
                **state,
                **updates,
            },
        )

        updates.update(result.update)

        if thread_id:
            await publish_tool_event(
                thread_id=thread_id,
                tool_name=tool_name,
                result=result,
            )

        tool_messages.append(
            {
                "role": "tool",
                "tool_call_id": tool_call["id"],
                "content": json.dumps(result.content),
            }
        )

    return {
        "messages": tool_messages,
        **updates,
    }