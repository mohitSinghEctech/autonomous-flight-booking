import asyncio

from app.providers.payment.cashfree import CashfreePaymentProvider


async def main():
    provider = CashfreePaymentProvider()

    result = await provider.create_payment(
        booking_id="test_booking_002",
        amount=100.0,
        currency="INR",
    )

    print("Payment result:")
    print(result)


if __name__ == "__main__":
    asyncio.run(main())