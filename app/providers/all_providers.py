from app.core.settings import settings
from app.providers.flights.base import FlightProvider
from app.providers.payment.base import PaymentProvider


def build_providers() -> tuple[FlightProvider, PaymentProvider]:
    if settings.provider_mode == "offline":
        from app.providers.offline import OfflineFlightProvider, OfflinePaymentProvider

        return OfflineFlightProvider(), OfflinePaymentProvider()

    from app.providers.flights.duffel import DuffelFlightProvider
    from app.providers.payment.cashfree import CashfreePaymentProvider

    return DuffelFlightProvider(), CashfreePaymentProvider()


flight_provider, payment_provider = build_providers()
