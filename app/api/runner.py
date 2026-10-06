from typing import Any

from app.agent.graph import graph
from app.api.event_bus import event_bus
from app.api.events import SSEEvent
from app.api.progress import (
    publish_error,
    publish_message,
    publish_step,
)


async def run_turn(
    thread_id: str,
    user_id: str,
    message: str,
) -> dict[str, Any]:

    try:
        await publish_step(
            thread_id,
            step="thinking",
            status="started",
        )

        config = {
            "configurable": {
                "thread_id": thread_id,
            }
        }

        result = await graph.ainvoke(
            {
                "messages": [
                    {
                        "role": "user",
                        "content": message,
                    }
                ],
                "user_id": user_id,
            },
            config=config,
        )

        await publish_step(
            thread_id,
            step="thinking",
            status="completed",
        )

        messages = result.get("messages", [])

        if messages:
            last_message = messages[-1]

            await publish_message(
                thread_id=thread_id,
                role=last_message.get("role"),
                content=last_message.get("content"),
            )

        return result

    except Exception as exc:

        await publish_error(
            thread_id,
            str(exc),
        )

        await publish_step(
            thread_id,
            step="thinking",
            status="failed",
            message=str(exc),
        )

        raise