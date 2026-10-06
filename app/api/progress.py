from app.api.event_bus import event_bus
from app.api.events import SSEEvent


async def publish_step(
    thread_id: str,
    step: str,
    status: str,
    message: str | None = None,
) -> None:

    data = {
        "step": step,
        "status": status,
    }

    if message is not None:
        data["message"] = message

    await event_bus.publish(
        thread_id,
        SSEEvent(
            event="step.updated",
            data=data,
        ),
    )


async def publish_message(
    thread_id: str,
    role: str,
    content: str | None,
) -> None:

    await event_bus.publish(
        thread_id,
        SSEEvent(
            event="message",
            data={
                "role": role,
                "content": content,
            },
        ),
    )


async def publish_error(
    thread_id: str,
    message: str,
) -> None:

    await event_bus.publish(
        thread_id,
        SSEEvent(
            event="error",
            data={
                "message": message,
            },
        ),
    )