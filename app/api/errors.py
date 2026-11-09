"""
One error shape for every non-2xx response (contract §9):

    {"error": {"code": "turn_in_progress", "message": "...", "retryable": true}}

ApiError is what routes raise. to_error_code() maps internal exceptions
(raised inside a turn) to a contract code + a message safe to show users.
"""
import httpx
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core import errors as app_errors


class ApiError(Exception):

    def __init__(self, status: int, code: str, message: str, retryable: bool = False):
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message
        self.retryable = retryable


def error_body(code: str, message: str, retryable: bool = False) -> dict:
    return {"error": {"code": code, "message": message, "retryable": retryable}}


def install_error_handlers(app: FastAPI) -> None:

    @app.exception_handler(ApiError)
    async def _api_error(request: Request, exc: ApiError):
        return JSONResponse(error_body(exc.code, exc.message, exc.retryable), status_code=exc.status)

    @app.exception_handler(RequestValidationError)
    async def _validation(request: Request, exc: RequestValidationError):
        first = exc.errors()[0] if exc.errors() else {}
        where = ".".join(str(part) for part in first.get("loc", []) if part != "body")
        message = f"{where}: {first.get('msg', 'invalid request')}" if where else "Invalid request."
        return JSONResponse(error_body("validation_error", message), status_code=422)

    @app.exception_handler(StarletteHTTPException)
    async def _http(request: Request, exc: StarletteHTTPException):
        code = {401: "unauthenticated", 403: "forbidden", 404: "session_not_found"}.get(exc.status_code, "internal_error")
        return JSONResponse(error_body(code, str(exc.detail)), status_code=exc.status_code)

    @app.exception_handler(Exception)
    async def _unexpected(request: Request, exc: Exception):
        return JSONResponse(error_body("internal_error", "Something went wrong. Please try again.", True), status_code=500)


def to_error_code(exc: Exception) -> tuple[str, str]:
    """(code, user-safe message) for an exception that escaped a turn."""

    if isinstance(exc, app_errors.UpstreamRateLimited):
        return "rate_limited", "The service is busy. Please try again in a moment."
    if isinstance(exc, (app_errors.UpstreamTimeout, app_errors.UpstreamUnavailable, httpx.TimeoutException, httpx.ConnectError)):
        return "provider_unavailable", "A travel or payment provider is not responding. Please try again."
    if isinstance(exc, app_errors.FlightNotFound):
        return "flight_not_found", str(exc)
    if isinstance(exc, app_errors.BookingNotPayable):
        return "booking_not_payable", str(exc)
    if isinstance(exc, app_errors.NoActiveBooking):
        return "no_active_booking", str(exc)
    if isinstance(exc, app_errors.PaymentNotFound):
        return "payment_not_found", str(exc)
    if isinstance(exc, httpx.HTTPStatusError):
        return "provider_error", f"The provider rejected the request ({exc.response.status_code})."
    if isinstance(exc, app_errors.AppError):
        return "provider_error", str(exc)
    return "internal_error", "Something went wrong. Please try again."
