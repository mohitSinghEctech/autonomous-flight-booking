import asyncio

from app.agent.graph import graph
from langgraph.types import Command


async def main():
    config = {
        "configurable": {
            "thread_id": "booking-payment-test-002"
        }
    }

    # Turn 1: create a booking hold
    result = await graph.ainvoke(
        {
            "messages": [
                {
                    "role": "user",
                    "content": (
                        "Find economy flights from DEL to DXB for 2 passengers "
                        "on 2026-10-10 and book the cheapest one."
                    ),
                }
            ],
            "user_id": "eeb6ff6a-c66f-4874-a5aa-7c773962e14e",
            "booking": None,
            "payment": None,
            "db_booking_id": None,
        },
        config=config,
    )

    interrupts = result.get("__interrupt__")

    if interrupts:
        interrupt_data = interrupts[0]

        print(interrupt_data.value["message"])

        approval = input("Your response (yes/no): ")

        result = await graph.ainvoke(
            Command(resume=approval),
            config=config,
        )

    print("\nBooking created:")
    print(result.get("booking"))

    # Turn 2: create payment for the existing booking
    result = await graph.ainvoke(
        {
            "messages": [
                {
                    "role": "user",
                    "content": "Create payment for my booking.",
                }
            ]
        },
        config=config,
    )

    print("\nPayment response:")
    print(result["messages"][-1].get("content"))
    
    print("\nFinal booking state:")
    print(result.get("booking"))
    
    result = await graph.ainvoke(
        {
            "messages": [
                {
                    "role": "user",
                    "content": "Complete the payment for my booking.",
                }
            ]
        },
        config=config,
    )

    print("\nPayment completion response:")
    print(result["messages"][-1].get("content"))

    print("\nFinal booking state:")
    print(result.get("booking"))

    print("\nFinal payment state:")
    print(result.get("payment"))


if __name__ == "__main__":
    asyncio.run(main())