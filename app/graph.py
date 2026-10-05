"""
Demo runner for the booking agent: search -> approve -> book -> pay.

The graph itself lives in app/agent/graph.py.
Run with: uv run python -m app.graph
"""
import asyncio

from langgraph.types import Command

from app.agent.graph import graph


def print_state(label: str, result: dict):
    print(f"\n{'=' * 20} {label} {'=' * 20}")

    print("\nBooking (provider view):")
    print(result.get("booking"))

    print("\nDatabase booking ID:")
    print(result.get("db_booking_id"))

    print("\nPayment:")
    print(result.get("payment"))

    print()


async def main():
    config = {
        "configurable": {
            "thread_id": "booking-001"
        }
    }

    result = await graph.ainvoke(
        {
            "messages": [
                {
                    "role": "user",
                    "content": "Find economy flights from DEL to DXB for 1 passenger on 2026-10-10 and book the cheapest one. Also provide me comparison for prices for different flights"
                }
            ],
            "user_id": "eeb6ff6a-c66f-4874-a5aa-7c773962e14e",
            "booking": None,
            "payment": None,
            "db_booking_id": None,
        },
        config=config
    )

    interrupts = result.get("__interrupt__")

    if interrupts:
        print(interrupts[0].value["message"])
        approval = input("Your response (yes/no): ")

        result = await graph.ainvoke(
            Command(resume=approval),
            config=config
        )

    if result.get("booking") is None:
        print(result["messages"][-1].get("content"))
        print("Stopping workflow")
        return

    print_state("BOOKING CREATED", result)

    result = await graph.ainvoke(
        {
            "messages": [
                {
                    "role": "user",
                    "content": "Create the payment for my booking."
                }
            ]
        },
        config=config
    )

    print_state("PAYMENT CREATED", result)

    result = await graph.ainvoke(
        {
            "messages": [
                {
                    "role": "user",
                    "content": "Complete the payment for my booking."
                }
            ]
        },
        config=config
    )

    print_state("PAYMENT COMPLETED", result)

    print(result["messages"][-1].get("content"))


if __name__ == "__main__":
    asyncio.run(main())
