class AppError(Exception):
    pass

class InvalidToolArguments(AppError):
    pass

class ToolNotFound(AppError):
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
