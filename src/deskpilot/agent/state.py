from typing import TypedDict, Annotated, List, Optional, Dict, Any
from langchain_core.messages import BaseMessage
import operator


class IntentResult(TypedDict):
    """Structured output from the intent classifier."""
    intent: str
    tool_name: str
    tool_args: Dict[str, Any]
    confidence: float
    raw_query: str


class AgentState(TypedDict):

    # Voice I/O
    user_input: str
    agent_response: str

    # Conversation history
    messages: Annotated[List[BaseMessage], operator.add]

    # Intent
    intent_result: IntentResult

    # Memory
    memory_context: str

    # Tool execution
    tool_name: str
    tool_args: Dict[str, Any]
    tool_output: str
    tool_success: bool

    # Safety
    needs_confirmation: bool
    confirmed: bool
    pending_tool: Dict[str, Any]

    # Session
    session_id: str
    turn_number: int
    error_message: str

    # Internal routing signal
    _routing_action: str