
"""
nodes.py  —  Hybrid Architecture

Each node is a thin wrapper. All real logic lives in:
  intent_classifier.py  → classify_intent()
  tool_router.py        → ToolRouter.route()
  tool_executor.py      → execute_tool()
  response_generator.py → generate_response()

Nodes only:
  1. Read from AgentState
  2. Call the right module
  3. Write results back to AgentState
"""

import logging

from langchain_core.messages import (
    HumanMessage,
    AIMessage,
)

from .state import AgentState
from .intent_classifier import classify_intent
from .tool_router import ToolRouter
from .tool_executor import execute_tool
from .response_generator import generate_response
from ..memory import memory as mem

logger = logging.getLogger("wpa.nodes")

_router = ToolRouter()


# ══════════════════════════════════════════════════════════════════════════════
# NODE 1 — Intent Classifier
# Input : user_input
# Output: intent_result
# ══════════════════════════════════════════════════════════════════════════════

def classify_node(state: AgentState) -> dict:
    """
    LLM classifies intent → structured JSON.
    No tool calls here.
    """

    user_input = state["user_input"]

    # logger.info(f"[classify_node] '{user_input}'")

    memory_context = mem.get_context(
        user_input
    )
    
    # Pass recent conversation history for context
    conversation_history = state.get("messages", [])
    
    # logger.info(f"[classify_node] Messages in history: {len(conversation_history)}")
    # if conversation_history:
    #     for i, msg in enumerate(conversation_history[-4:]):
    #         role = "User" if msg.type == "human" else "Agent"
    #         logger.info(f"  [{i}] {role}: {msg.content[:60]}...")
    
    intent_result = classify_intent(
        user_input, 
        memory_context=memory_context,
        conversation_history=conversation_history
    )

    return {
        "intent_result": intent_result,
        "messages": [HumanMessage(content=user_input)],
        "turn_number": state.get("turn_number", 0) + 1,
    }


# ══════════════════════════════════════════════════════════════════════════════
# NODE 2 — Deterministic Router
# Input : intent_result + pending_tool
# Output: tool_name, tool_args, needs_confirmation, action routing signal
# ══════════════════════════════════════════════════════════════════════════════

def route_node(state: AgentState) -> dict:
    """
    Pure Python routing.

    Decides what happens next.

    Stores routing decision in state for the
    conditional edge to read.
    """

    intent_result = state.get("intent_result", {})
    pending_tool = state.get("pending_tool", {})

    action, payload, needs_confirm = _router.route(
        intent_result,
        pending_tool,
    )

    # logger.info(
    #     f"[route_node] action={action} payload={payload}"
    # )

    update = {
        "tool_name": payload.get("tool_name", ""),
        "tool_args": payload.get("tool_args", {}),
        "needs_confirmation": needs_confirm,

        # Store action in agent_response temporarily
        # so the conditional edge can read it
        "_routing_action": action,
    }

    # If this is a risky tool,
    # save it as pending for after confirmation
    if action == "confirm":

        update["pending_tool"] = payload
        update["confirmed"] = False

    # If user confirmed, clear pending
    if action == "confirmed":

        update["confirmed"] = True
        update["pending_tool"] = {}

    # If user cancelled, clear pending
    if action == "cancelled":

        update["confirmed"] = False
        update["pending_tool"] = {}

        update["tool_name"] = ""
        update["tool_args"] = {}

    return update


# ══════════════════════════════════════════════════════════════════════════════
# NODE 3 — Tool Executor
# Input : tool_name, tool_args
# Output: tool_output, tool_success
# ══════════════════════════════════════════════════════════════════════════════

def execute_node(state: AgentState) -> dict:
    """
    Runs the tool.

    Pure Python.
    No LLM.
    """

    tool_name = state.get("tool_name", "")
    tool_args = state.get("tool_args", {})

    success, output = execute_tool(
        tool_name,
        tool_args,
    )

    # logger.info(
    #     f"[execute_node] {tool_name} "
    #     f"-> success={success} "
    #     f"output={output[:80]}"
    # )

    return {
        "tool_output": output,
        "tool_success": success,

        "messages": [
            AIMessage(
                content=f"[tool:{tool_name}] {output}"
            )
        ],
    }


# ══════════════════════════════════════════════════════════════════════════════
# NODE 4 — Response Generator
# Input : routing action + tool results + user_input + history
# Output: agent_response (natural spoken text)
# ══════════════════════════════════════════════════════════════════════════════

def respond_node(state: AgentState) -> dict:
    """
    LLM formats the result into spoken language.

    No decisions here.
    """

    action = state.get("_routing_action", "chat")

    tool_name = state.get("tool_name", "")
    tool_args = state.get("tool_args", {})

    tool_output = state.get("tool_output", "")
    tool_success = state.get("tool_success", False)

    user_input = state.get("user_input", "")
    history = state.get("messages", [])

    # Map action → response_type
    if action in ("execute", "confirmed"):

        response_type = (
            "tool_success"
            if tool_success
            else "tool_failure"
        )

    elif action == "confirm":
        response_type = "confirm"

    elif action == "cancelled":
        response_type = "cancel"

    elif action == "clarify":
        response_type = "clarify"

    else:
        response_type = "chat"

    text = generate_response(
        response_type=response_type,
        tool_name=tool_name,
        tool_args=tool_args,
        tool_output=tool_output,
        user_input=user_input,
        history=history,
    )

    # logger.info(
    #     f"[respond_node] "
    #     f"response_type={response_type} "
    #     f"text='{text[:80]}'"
    # )

    return {
        "agent_response": text,

        "messages": [
            AIMessage(content=text)
        ],
    }


# ══════════════════════════════════════════════════════════════════════════════
# NODE 5 — Memory  (NEW — pure Python, always runs last)
# ══════════════════════════════════════════════════════════════════════════════

def memory_node(state: AgentState) -> dict:

    """
    Saves the completed turn to memory.

    Always runs last. Never modifies agent_response.

    Pure Python — no LLM call.


    Also detects "remember" commands from the user:

      "remember that I prefer dark mode"

      "my downloads folder is D:/Downloads"
    """

    user_input = state.get(
        "user_input",
        ""
    )

    session_id = state.get(
        "session_id",
        "unknown"
    )

    intent = state.get(
        "intent_result",
        {}
    ).get(
        "intent",
        ""
    )

    tool_name = state.get(
        "tool_name",
        ""
    )

    tool_args = state.get(
        "tool_args",
        {}
    )

    tool_output = state.get(
        "tool_output",
        ""
    )

    tool_success = state.get(
        "tool_success",
        False
    )

    response = state.get(
        "agent_response",
        ""
    )


    # ── Save this turn to SQLite + ChromaDB ───────────────────────────────────

    mem.save_turn(

        session_id=session_id,

        user_input=user_input,

        intent=intent,

        tool_name=tool_name,

        tool_args=tool_args,

        tool_output=tool_output,

        success=tool_success,

        response=response,
    )


    # ── Detect explicit "remember" commands ───────────────────────────────────

    lower = user_input.lower()


    remember_triggers = [

        "remember that",

        "remember this",

        "don't forget",

        "note that",

        "save this",

        "my preference is",

        "i prefer",

        "i always",

        "my favourite",

        "my favorite",
    ]


    for trigger in remember_triggers:

        if trigger in lower:

            # Extract the fact after the trigger word

            idx = (
                lower.index(trigger)
                + len(trigger)
            )

            fact = (

                user_input[idx:]

                .strip()

                .strip(".,!?")
            )


            if fact:

                mem.remember(fact)

                # logger.info(
                #     f"[memory_node] stored explicit preference: '{fact}'"
                # )

            break


    # logger.info(

    #     f"[memory_node] turn saved | "

    #     f"session={session_id} "

    #     f"tool={tool_name}"

    # )


    # Memory node never changes agent_response — return empty dict

    return {}


# ══════════════════════════════════════════════════════════════════════════════
# ROUTERS  —  Conditional edge functions
# These read _routing_action from state
# and return the next node name
# ══════════════════════════════════════════════════════════════════════════════

def route_after_classify(state: AgentState) -> str:
    """
    After classify:
    always go to route_node.
    """

    return "route"


def route_after_route(state: AgentState) -> str:
    """
    After route_node:
    decide next node based on action.

    execute   → run the tool
    confirmed → run the tool (after user said yes)

    confirm   → skip execution,
                 go straight to respond

    cancelled → skip execution,
                 go straight to respond

    chat      → skip execution,
                 go straight to respond

    clarify   → skip execution,
                 go straight to respond
    """

    action = state.get("_routing_action", "chat")

    # logger.info(
    #     f"[router_edge] action={action}"
    # )

    if action in ("execute", "confirmed"):
        return "execute"

    return "respond"
