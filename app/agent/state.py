import operator
from typing import Annotated, TypedDict


class AgentState(TypedDict):
    messages: Annotated[list, operator.add]
    user_id: str

    booking: dict | None
    payment: dict | None

    db_booking_id: str | None

    unavailable_offers: list[str]
