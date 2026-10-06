from contextlib import asynccontextmanager

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool
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


def build_graph(checkpointer=None):

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
        checkpointer=checkpointer or InMemorySaver()
    )


# In memory until the API starts: tests and `python -m app.graph` use this one.
graph = build_graph()


@asynccontextmanager
async def postgres_checkpointer(database_url: str):
    """
    The agent's memory (messages, booking state, a paused interrupt) in Postgres,
    so an approval waiting when the API restarts can still be answered.

    Used by the app's lifespan (main.py). Callers reach the graph as
    `agent_graph.graph`, so swapping it here is enough.
    """
    global graph

    # LangGraph's saver speaks psycopg, not asyncpg: same database, plain URL
    conninfo = database_url.replace("postgresql+asyncpg://", "postgresql://")

    async with AsyncConnectionPool(
        conninfo,
        min_size=1,
        max_size=5,
        open=False,
        kwargs={"autocommit": True, "prepare_threshold": 0, "row_factory": dict_row},
    ) as pool:
        saver = AsyncPostgresSaver(pool)
        await saver.setup()            # creates / migrates LangGraph's own tables

        previous, graph = graph, build_graph(saver)
        try:
            yield
        finally:
            graph = previous
