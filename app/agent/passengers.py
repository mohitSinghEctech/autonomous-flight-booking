"""
Passenger-required workflow (contract v1.1).

The LLM calls `request_passenger_details` when the trip needs more travellers
than are saved (or a saved one is incomplete). This node pauses the graph with
interrupt(); the browser shows a form; POST /passenger-requests/{id} saves the
passengers in Postgres and resumes the graph with their ids. The LLM then books
with the full passenger list — still behind the normal booking approval.

    LLM ─ request_passenger_details ─► passengers node ─ interrupt ─► UI form
         ◄────────── tool reply {added_passengers: [...]} ◄── resume ──┘
"""
import json

from langgraph.types import interrupt

from app.agent.approval import skip_tool_calls, supersede
from app.agent.handlers import current_user_id
from app.agent.state import AgentState
from app.api.events import PASSENGER_FIELDS
from app.api.views import passenger_view
from app.db.session import SessionLocal
from app.services.booking import BookingService


TOOL_NAME = "request_passenger_details"


async def passengers_node(state: AgentState):

    tool_calls = state["messages"][-1]["tool_calls"]
    call = next(tc for tc in tool_calls if tc["function"]["name"] == TOOL_NAME)

    try:
        args = json.loads(call["function"]["arguments"] or "{}")
    except json.JSONDecodeError:
        args = {}

    needed = max(1, min(int(args.get("count") or 1), 9))

    async with SessionLocal() as session:
        saved = await BookingService(session).list_passengers(current_user_id(state))

    request = {
        "request_id": f"pr_{call['id']}",          # stable across the node's re-run on resume
        "needed": needed,
        "existing": [passenger_view(p) for p in saved],
        "fields": PASSENGER_FIELDS,
        "message": args.get("reason") or f"I need details for {needed} more passenger{'s' if needed > 1 else ''}.",
    }

    answer = interrupt({"type": "passengers", "request": request})

    if answer.get("decision") == "superseded":
        return supersede(tool_calls, "The user moved on to a different request.")

    if answer.get("decision") != "provided":
        return skip_tool_calls(tool_calls, "The user did not add passenger details.")

    replies = [
        {
            "role": "tool",
            "tool_call_id": call["id"],
            "content": json.dumps({
                "added_passengers": answer["passengers"],
                "note": "Use these ids together with the saved passengers' ids.",
            }),
        }
    ]

    # any other tool call in the same message was not run: say so
    others = [tc for tc in tool_calls if tc["id"] != call["id"]]
    replies += skip_tool_calls(others, "Not run: call it again now that passengers are added.")["messages"]

    return {"messages": replies}
