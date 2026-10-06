import asyncio
import logging
import os
import time

from dotenv import load_dotenv
from openai import APIConnectionError, APITimeoutError, AsyncOpenAI, RateLimitError

from app.agent.state import AgentState
from app.api import progress
from app.core.errors import (
    InvalidUpstreamResponse,
    UpstreamRateLimited,
    UpstreamTimeout,
    UpstreamUnavailable,
)
from app.core.logging import log_fields
from app.core.rate_limiter import llm_rate_limiter
from app.models import BookFlight, SearchFlights


load_dotenv()

logger = logging.getLogger(__name__)

llm_semaphore = asyncio.Semaphore(3)

client = AsyncOpenAI(
    api_key=os.getenv("LLM_API_KEY"),
)


NO_ARGUMENTS = {
    "type": "object",
    "properties": {},
    "additionalProperties": False,
}

# What the LLM is allowed to ask for. Each name maps to a handler in tools.py.
TOOLS = [
    {
        "name": "search_flights",
        "description": (
            "Search for available flights. "
            "origin and destination must be IATA airport codes, "
            "such as DEL for Delhi and DXB for Dubai."
        ),
        "parameters": SearchFlights.model_json_schema(),
    },
    {
        "name": "book_flight",
        "description": (
            "Place a selected flight on hold. "
            "This does not complete payment or confirm the booking. "
            "flight_id must be the exact flight_id returned by search_flights. "
            "passenger_ids must be IDs returned by get_saved_passengers."
        ),
        "parameters": BookFlight.model_json_schema(),
    },
    {
        "name": "get_saved_passengers",
        "description": (
            "Get the passengers saved in the customer's profile. "
            "Use their passenger IDs when booking a flight."
        ),
        "parameters": NO_ARGUMENTS,
    },
    {
        "name": "request_passenger_details",
        "description": (
            "Ask the user to add passenger details that are not saved yet. "
            "Call this ALONE (no other tool in the same message) when the trip needs more "
            "passengers than get_saved_passengers returned, or when a saved passenger has "
            "missing_details. count = how many new passengers are needed. "
            "Never invent passenger names or details."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "count": {"type": "integer", "minimum": 1, "maximum": 9},
                "reason": {"type": "string", "description": "One short sentence shown to the user."},
            },
            "required": ["count"],
            "additionalProperties": False,
        },
    },
    {
        "name": "create_payment",
        "description": (
            "Create a payment for the current held booking. "
            "Use this only when the current booking lifecycle is HELD "
            "and the user wants to start the payment process. "
            "Do not use this for a booking that is already AWAITING_PAYMENT "
            "or when the user wants to complete an existing payment."
        ),
        "parameters": NO_ARGUMENTS,
    },
    {
        "name": "complete_payment",
        "description": (
            "Complete the existing payment for the current booking. "
            "Use this when a payment has already been created and the user "
            "wants to complete or pay for it. "
            "Do not create a new payment."
        ),
        "parameters": NO_ARGUMENTS,
    },
]


GUIDE = (
    "You are ATLAS, a flight booking assistant. "
    "Search with search_flights, check travellers with get_saved_passengers, then book with book_flight "
    "using passenger ids for exactly the number of passengers searched. "
    "The application asks the user to approve every booking; do not ask for confirmation yourself. "
    "If a tool error says retryable is false, do not call that tool again with the same arguments; explain the reason and offer an alternative (for an unavailable fare: search again). "
    "If a flight_id is given by the user, use that exact flight. "
    "If passengers are missing or incomplete, call request_passenger_details. "
    "Payments happen with buttons in the app; you don't need to collect card details. "
    "Messages starting with [app] are facts from the application about changes made outside the chat; "
    "they override anything said earlier. Booking states: held or awaiting_payment = active; "
    "confirmed = paid; cancelled or expired = no active booking, so you may book again. "
    "Keep replies short."
)


def build_messages(state: AgentState) -> list[dict]:
    """Conversation history, plus the app's booking/payment state if any."""

    messages = [{"role": "system", "content": GUIDE}, *state["messages"]]

    booking = state.get("booking")
    payment = state.get("payment")

    if booking:
        payment_status = payment["status"] if payment else "none"

        messages.insert(
            1,
            {
                "role": "system",
                "content": (
                    f"Application booking state: {booking['lifecycle']}. "
                    f"Application payment state: {payment_status}. "

                    "If the booking lifecycle is HELD and the user wants to start "
                    "payment, call create_payment. "

                    "If the payment status is CREATED and the user wants to complete "
                    "the payment, call complete_payment. "

                    "Do not ask the user for booking ID, payment ID, amount, or currency. "
                    "The application provides those values."
                ),
            },
        )

    return messages


async def call_llm(state: AgentState):
    started = time.monotonic()
    try:
        await llm_rate_limiter.acquire()

        async with llm_semaphore:
            response = await client.chat.completions.create(
                model=os.getenv("LLM_MODEL"),
                messages=build_messages(state),
                tools=[
                    {"type": "function", "function": tool}
                    for tool in TOOLS
                ],
            )

        if not response.choices:
            raise InvalidUpstreamResponse("LLM provider returned an empty response.")

    except APITimeoutError as exc:
        raise UpstreamTimeout("LLM request timed out.") from exc
    except RateLimitError as exc:
        raise UpstreamRateLimited("LLM rate limit exceeded.") from exc
    except APIConnectionError as exc:
        raise UpstreamUnavailable("LLM provider currently unavailable.") from exc

    usage = getattr(response, "usage", None)
    input_tokens = getattr(usage, "prompt_tokens", 0) or 0
    output_tokens = getattr(usage, "completion_tokens", 0) or 0

    turn = progress.current_turn()
    if turn:
        turn.input_tokens += input_tokens
        turn.output_tokens += output_tokens

    message = response.choices[0].message.model_dump()
    log_fields(
        logger, "llm call",
        model=os.getenv("LLM_MODEL"),
        duration_ms=round((time.monotonic() - started) * 1000),
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        tool_calls=[c["function"]["name"] for c in (message.get("tool_calls") or [])],
    )

    return {
        "messages": [message]
    }


FALLBACK_REPLIES = {
    UpstreamTimeout: (
        "I'm sorry, but the flight service is temporarily unavailable. "
        "Please try again."
    ),
    UpstreamRateLimited: (
        "The AI service is currently receiving too many "
        "requests. Please try again shortly."
    ),
    UpstreamUnavailable: (
        "The AI service is currently unavailable. "
        "Please try again shortly."
    ),
    InvalidUpstreamResponse: (
        "I received an invalid response from the AI service. "
        "Please try again."
    ),
}


async def safe_call_llm(state: AgentState):
    """LLM node: reports a step, publishes any text it says, and turns upstream
    failures into a polite assistant reply."""

    turn = progress.current_turn()
    first = turn is None or turn.llm_calls == 0
    if turn:
        turn.llm_calls += 1

    step_id = await progress.start_step(
        "llm",
        "Understanding your request" if first else "Deciding the next step",
        stage="thinking",
        status_text="Thinking…",
    )

    try:
        result = await call_llm(state)
        step_status = "done"
    except tuple(FALLBACK_REPLIES) as exc:
        result = {
            "messages": [
                {"role": "assistant", "content": FALLBACK_REPLIES[type(exc)]}
            ]
        }
        step_status = "failed"

    await progress.finish_step(step_id, status=step_status)

    text = (result["messages"][0].get("content") or "").strip()
    if text:
        await progress.publish_message("assistant", text)

    return result
