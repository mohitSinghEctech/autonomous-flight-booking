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

