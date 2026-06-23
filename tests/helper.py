# ─── Helper to run one turn ───────────────────────────────────────────────────
import uuid
import sys
from pathlib import Path

from langchain_core.messages import BaseMessage

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.wpa.agent import agent, AgentState

conversation_history = []
SESSION_ID = str(uuid.uuid4())[:8]

def run_turn(user_input: str) -> str:
    global conversation_history
    
    state = AgentState(
        user_input         = user_input,
        agent_response     = "",
        messages           = conversation_history,
        intent             = "",
        plan               = [],
        tool_calls_made    = [],
        tool_results       = [],
        retry_count        = 0,
        needs_confirmation = False,
        confirmed          = False,
        session_id         = SESSION_ID,
        turn_number        = len(conversation_history) // 2,
    )
    
    result = agent.invoke(state)
    conversation_history = result["messages"]
    
    response = result["agent_response"]
    tools    = result.get("tool_calls_made", [])
    
    print(f"\n👤 {user_input}")
    if tools:
        print(f"   🔧 Tools used: {tools}")
    print(f"🤖 {response}")
    return response

# print("✅ run_turn() ready")
# run_turn("set the volume to 30%")
# run_turn("Hello, what can you do?")
run_turn("what is the capital of France?")