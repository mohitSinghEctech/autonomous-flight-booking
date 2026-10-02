import asyncio

from app.providers.all_providers import payment_provider


async def main():
    result = await payment_provider.create_payment(
        booking_id="ord_test_123",
        amount=205.44,
        currency="GBP",
    )

    print("Payment result:")
    print(result)


if __name__ == "__main__":
    asyncio.run(main())