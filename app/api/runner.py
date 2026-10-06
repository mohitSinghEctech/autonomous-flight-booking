from typing import Any

from langgraph.types import Command

from app.agent.graph import graph
from app.api.event_bus import event_bus
from app.api.events import SSEEvent
from app.api.progress import (
    publish_error,
    publish_message,
    publish_step,
)


def build_config(
    thread_id: str,
) -> dict:

    return {
        "configurable": {
            "thread_id": thread_id,
        }
    }


async def run_turn(
    thread_id: str,
    user_id: str,
    message: str,
) -> dict[str, Any]:

    try:

        await publish_step(
            thread_id,
            "thinking",
            "started",
        )

        result = await graph.ainvoke(
            {
                "messages": [
                    {
                        "role": "user",
                        "content": message,
                    }
                ],
                # Only what is NEW this turn. Passing booking/payment = None here
                # would overwrite the checkpointed state and forget the booking.
                # thread_id is NOT state: nodes read it from config.
                "user_id": user_id,
            },
            config=build_config(thread_id),
        )

        # -----------------------------------------------------
        # LangGraph paused at interrupt()
        # -----------------------------------------------------

        interrupts = result.get("__interrupt__")

        if interrupts:

            # Published here, once, from the interrupt value. Not inside
            # approval_node: on resume LangGraph re-runs that node from the top.
            await event_bus.publish(
                thread_id,
                SSEEvent(
                    event="approval.required",
                    data=interrupts[0].value,
                ),
            )

            await publish_step(
                thread_id,
                "approval",
                "waiting",
            )

            return {
                "result": result,
                "waiting_for_approval": True,
            }

        await publish_step(
            thread_id,
            "thinking",
            "completed",
        )

        await publish_last_message(
            thread_id,
            result,
        )

        return {
            "result": result,
            "waiting_for_approval": False,
        }

    except Exception as exc:

        await publish_error(
            thread_id,
            str(exc),
        )

        await publish_step(
            thread_id,
            "thinking",
            "failed",
            str(exc),
        )

        raise


async def resume_turn(
    thread_id: str,
    approval: bool,
) -> dict[str, Any]:

    try:

        await publish_step(
            thread_id,
            "approval",
            "resuming",
        )

        result = await graph.ainvoke(
            Command(
                resume=approval,
            ),
            config=build_config(thread_id),
        )

        await publish_step(
            thread_id,
            "approval",
            "completed",
        )

        await publish_step(
            thread_id,
            "thinking",
            "completed",
        )

        await publish_last_message(
            thread_id,
            result,
        )

        return result

    except Exception as exc:

        await publish_error(
            thread_id,
            str(exc),
        )

        await publish_step(
            thread_id,
            "approval",
            "failed",
            str(exc),
        )

        raise


async def publish_last_message(
    thread_id: str,
    result: dict,
) -> None:

    messages = result.get("messages", [])

    if not messages:
        return

    last_message = messages[-1]

    await publish_message(
        thread_id=thread_id,
        role=last_message.get("role"),
        content=last_message.get("content"),
    )