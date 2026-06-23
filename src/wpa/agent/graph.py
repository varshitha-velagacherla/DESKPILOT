
"""
graph.py  

Flow:
  classify → route → execute → respond → memory → END
                  ↘           ↗
                   respond (chat/confirm/clarify/cancel)
                        ↓
                    memory → END

Reading this file should make the entire flow obvious in 30 seconds.
"""

from langgraph.graph import StateGraph, END

from .state import AgentState

from .nodes import (
    classify_node,
    memory_node,
    route_node,
    execute_node,
    respond_node,
    route_after_route,
)


def build_graph():

    g = StateGraph(AgentState)

    # ── Nodes ─────────────────────────────────────────────────────────────────

    g.add_node(
        "classify",
        classify_node
    )   # LLM → structured JSON intent

    g.add_node(
        "route",
        route_node
    )   # pure Python → routing decision

    g.add_node(
        "execute",
        execute_node
    )   # pure Python → run tool

    g.add_node(
        "respond",
        respond_node
    )   # LLM → natural spoken response
    
    g.add_node(
        "memory",
        memory_node
    )   # pure Python → save to memory

    # ── Entry ─────────────────────────────────────────────────────────────────

    g.set_entry_point("classify")

    # ── Edges ─────────────────────────────────────────────────────────────────

    g.add_edge(
        "classify",
        "route"
    )

    g.add_conditional_edges(
        "route",
        route_after_route,

        {
            "execute": "execute",   # tool_use or confirmed
            "respond": "respond",   # chat / confirm / clarify / cancel
        }
    )

    g.add_edge(
        "execute",
        "respond"
    )

    g.add_edge(
        "respond",
        "memory"
    )

    g.add_edge(
        "memory",
        END
    )

    return g.compile()


agent = build_graph()
