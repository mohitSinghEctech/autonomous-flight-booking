import operator
from typing import Annotated, TypedDict


class AgentState(TypedDict):
    # operator.add is a reducer: nodes return only their NEW messages and
    # LangGraph appends them, so history survives across turns.
    messages: Annotated[list, operator.add]
    user_id: str

    # What the LLM is shown. booking.booking_id is the PROVIDER's ID (Duffel).
    booking: dict | None
    payment: dict | None

    # Our own Postgres bookings.id. Used by services, never shown to the LLM.
    db_booking_id: str | None
