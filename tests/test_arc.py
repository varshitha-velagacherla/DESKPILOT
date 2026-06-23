"""
Run from project root:
python -m tests.test_arc

Supports:
  - Single turn: run_turn("open notepad")
  - Full conversation loop with confirmation handling
  - Debug mode that shows intent + routing at each step
"""

import sys
import uuid
import logging
from pathlib import Path

# ── Path setup ────────────────────────────────────────────────────────────────
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from src.wpa.agent import agent, AgentState

# ── Logging ───────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",

    handlers=[
        logging.FileHandler("logs/agent.log"),
        logging.StreamHandler(sys.stdout),
    ]
)

# Reduce noise from httpx/httpcore
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)

# ── Session state ─────────────────────────────────────────────────────────────
conversation_history = []
pending_tool = {}

SESSION_ID = str(uuid.uuid4())[:8]


def run_turn(user_input: str, debug: bool = False) -> str:
    """
    Run one conversation turn through the hybrid agent.

    Args:
        user_input: what the user said
        debug: if True, print intent + routing details

    Returns:
        agent_response string
    """

    global conversation_history
    global pending_tool

    state = AgentState(

        # Voice I/O
        user_input=user_input,
        agent_response="",

        # History
        messages=conversation_history,

        # Intent (populated by classify_node)
        intent_result={},

        # Tool execution
        tool_name="",
        tool_args={},
        tool_output="",
        tool_success=False,

        # Safety
        needs_confirmation=False,
        confirmed=False,

        # Pass pending_tool from previous turn
        pending_tool=pending_tool,

        # Session
        session_id=SESSION_ID,
        turn_number=len(conversation_history) // 2,
        error_message="",

        # Internal routing signal
        _routing_action="",
    )

    result = agent.invoke(state)

    # ── Update session state ──────────────────────────────────────────────────

    conversation_history = result.get("messages", [])

    # Carry pending_tool forward if agent asked for confirmation
    action = result.get("_routing_action", "")

    if action == "confirm":
        pending_tool = result.get("pending_tool", {})

    else:
        pending_tool = {}

    # ── Extract results ───────────────────────────────────────────────────────

    response = result.get("agent_response", "")

    tools_used = result.get("tool_name", "")

    tool_success = result.get("tool_success", False)

    intent = result.get("intent_result", {})

    # ── Print output ──────────────────────────────────────────────────────────

    print(f"\n{'─' * 55}")

    print(f"You : {user_input}")

    if debug:

        print(
            f"     intent     = {intent.get('intent')} "
            f"(conf={intent.get('confidence', 0):.2f})"
        )

        print(
            f"     tool       = "
            f"{intent.get('tool_name')}"
        )

        print(
            f"     args       = "
            f"{intent.get('tool_args')}"
        )

        print(
            f"     action     = {action}"
        )

    if tools_used:

        if action == "confirm":
            status = "PENDING"

        elif action in ("execute", "confirmed"):
            status = "OK" if tool_success else "FAIL"

        else:
            status = "SKIPPED"

        print(
            f"     [{status}] tool: {tools_used}"
        )

        if debug and result.get("tool_output"):

            print(
                f"     output: "
                f"{result.get('tool_output', '')[:120]}"
            )

    if action == "confirm":

        print(f"WPA : {response}")

        print(
            f"     >>> Say 'yes' to confirm "
            f"or 'no' to cancel"
        )

    else:
        print(f"WPA : {response}")

    return response


def reset():
    """
    Reset conversation memory and pending state.
    """

    global conversation_history
    global pending_tool

    conversation_history = []
    pending_tool = {}

    print(f"\n{'─' * 55}")

    print("Session reset.")


# ── Quick test suite ──────────────────────────────────────────────────────────

if __name__ == "__main__":

    from pathlib import Path

    Path("logs").mkdir(exist_ok=True)

    print("=" * 55)

    print(
        "Windows Productivity Agent "
        "— Hybrid Architecture"
    )

    print(f"Session: {SESSION_ID}")

    print("=" * 55)

    # # Test 1: Pure chat — no tool should be called
    # print("\n[TEST 1] Pure chat")

    # run_turn(
    #     "Hello, what is your name?",
    #     debug=True
    # )

    # # Test 2: Chat capability question — no tool
    # print("\n[TEST 2] Capability question")

    # run_turn(
    #     "What can you do?",
    #     debug=True
    # )

    # Test 3: Time — should call get_current_time
    # print("\n[TEST 3] Time query")

    # run_turn(
    #     "What is the current time?",
    #     debug=True
    # )

    # Test 4: System info — should call get_system_info
    # print("\n[TEST 4] System info")

    # run_turn(
    #     "How is my CPU and battery?",
    #     debug=True
    # )

    # # Test 5: Open app — should call open_app
    # print("\n[TEST 5] Open app")

    # run_turn(
    #     "Open Notepad",
    #     debug=True
    # )

    # # Test 6: Risky tool — should ask for confirmation
    # print("\n[TEST 6] Risky tool (volume)")

    # run_turn(
    #     "Set the volume to 40 percent",
    #     debug=True
    # )

    # # Test 7: Confirm
    # print("\n[TEST 7] Confirm risky tool")

    # run_turn(
    #     "Yes go ahead",
    #     debug=True
    # )

    # # Test 8: Another risky tool then cancel
    # reset()

    # print("\n[TEST 8] Risky tool then cancel")

    # run_turn(
    #     "Set the volume to 80",
    #     debug=True
    # )

    # run_turn(
    #     "No cancel that",
    #     debug=True
    # )

    # # Test 9: Memory
    # print("\n[TEST 9] Conversation memory")

    # run_turn(
    #     "What did I just ask you?",
    #     debug=True
    # )
    temp = input("\nRun interactive session?(y/n) (type 'exit' to quit): ")
    while temp == "y":
        user_input = input("\nYou : ")
        if user_input.lower() in ("exit", "quit"):
            print("Exiting...")
            break
        run_turn(user_input, debug=True)
    print("Session ended.")
    
