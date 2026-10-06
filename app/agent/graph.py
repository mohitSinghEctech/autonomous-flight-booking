from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph

from app.agent.approval import approval_node
from app.agent.llm import safe_call_llm
from app.agent.passengers import TOOL_NAME as PASSENGER_TOOL, passengers_node
from app.agent.state import AgentState
from app.agent.tools import execute_tools


def route_after_llm(state: AgentState):

    last_message = state["messages"][-1]

    tool_calls = last_message.get("tool_calls") or []
    names = {tool_call["function"]["name"] for tool_call in tool_calls}

    # missing passengers first: there is nothing to approve without them
    if PASSENGER_TOOL in names:
        return "passengers"

    # book_flight never runs before a human says yes
    if "book_flight" in names:
        return "approval"

    if tool_calls:
        return "tools"

    return END


def route_after_approval(state: AgentState):
    """Approved -> tools (book). Declined -> llm (tell the user). Superseded -> END."""

    last = state["messages"][-1]

    if last["role"] == "tool":
        return "llm"

    # approved: the last message is still the assistant's tool call -> run it
    if last.get("tool_calls"):
        return "tools"

    # superseded: approval_node closed it with a plain assistant line
    return END


def route_after_passengers(state: AgentState):
    """Passengers added (or not) -> llm continues. Superseded -> END."""

    return END if state["messages"][-1]["role"] == "assistant" else "llm"


def build_graph():

    builder = StateGraph(AgentState)

    builder.add_node(
        "llm",
        safe_call_llm,
    )

    builder.add_node(
        "approval",
        approval_node,
    )

    builder.add_node(
        "tools",
        execute_tools,
    )

    builder.add_node(
        "passengers",
        passengers_node,
    )

    builder.add_edge(
        START,
        "llm",
    )

    builder.add_conditional_edges(
        "llm",
        route_after_llm,
        {
            "passengers": "passengers",
            "approval": "approval",
            "tools": "tools",
            END: END,
        },
    )

    builder.add_conditional_edges(
        "approval",
        route_after_approval,
        {
            "tools": "tools",
            "llm": "llm",
            END: END,
        },
    )

    builder.add_conditional_edges(
        "passengers",
        route_after_passengers,
        {
            "llm": "llm",
            END: END,
        },
    )

    builder.add_edge(
        "tools",
        "llm",
    )

    return builder.compile(
        checkpointer=InMemorySaver()
    )


graph = build_graph()