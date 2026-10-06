from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph

from app.agent.approval import approval_node
from app.agent.llm import safe_call_llm
from app.agent.state import AgentState
from app.agent.tools import execute_tools


def route_after_llm(state: AgentState):

    last_message = state["messages"][-1]

    tool_calls = last_message.get("tool_calls") or []

    for tool_call in tool_calls:

        if tool_call["function"]["name"] == "book_flight":
            return "approval"

    if tool_calls:
        return "tools"

    return END


def route_after_approval(state: AgentState):

    if state["messages"][-1]["role"] == "tool":
        return "llm"

    return "tools"


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

    builder.add_edge(
        START,
        "llm",
    )

    builder.add_conditional_edges(
        "llm",
        route_after_llm,
        {
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