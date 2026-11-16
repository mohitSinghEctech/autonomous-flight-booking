class AppError(Exception):
    pass

class InvalidToolArguments(AppError):
    pass

class FlightNotFound(AppError):
    pass

class InsufficientSeats(AppError):
    pass

class UpstreamTimeout(AppError):
    pass

class UpstreamRateLimited(AppError):
    pass

class UpstreamUnavailable(AppError):
    pass

class InvalidUpstreamResponse(AppError):
    pass

class PassengerNotFound(AppError):
    pass

class PassengerInUse(AppError):
    """The saved passenger is on a booking whose payment is still open."""

    def __init__(self, booking_reference: str, payment_required_by):
        self.booking_reference = booking_reference
        self.payment_required_by = payment_required_by
        super().__init__(
            f"This passenger is on booking {booking_reference}, which is awaiting payment "
            f"until {payment_required_by.isoformat()}. Finish or cancel that payment first, "
            "or try again after the deadline."
        )

class BookingNotPayable(AppError):
    pass

class NoActiveBooking(AppError):
    pass

class PaymentNotFound(AppError):
    pass


class OfferUnavailable(AppError):
    """The airline no longer sells this fare. Retrying the same offer always fails."""

    def __init__(self, flight_id: str):
        self.flight_id = flight_id
        super().__init__(
            "This fare is no longer available from the airline. "
            "Do not retry this flight; search again for current fares."
        )


class ProviderError(AppError):
    pass
