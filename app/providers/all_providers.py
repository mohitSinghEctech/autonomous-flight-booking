from app.providers.flights.duffel import DuffelFlightProvider
from app.providers.payment.cashfree import CashfreePaymentProvider


flight_provider = DuffelFlightProvider()
payment_provider = CashfreePaymentProvider()