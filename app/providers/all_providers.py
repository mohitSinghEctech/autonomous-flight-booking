from app.providers.flights.mock import MockFlightProvider
from app.providers.payment.mock import MockPaymentProvider

from app.providers.flights.duffel import DuffelFlightProvider
from app.providers.payment.cashfree import CashfreePaymentProvider


flight_provider = DuffelFlightProvider()
payment_provider = CashfreePaymentProvider()