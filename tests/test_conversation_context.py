"""
Test conversation context handling
"""
from src.wpa.agent import agent, AgentState

conversation_memory = []
pending_tool = {}
SESSION_ID = "test-session"

def test_agent(user_input: str):
    global conversation_memory, pending_tool
    
    state = AgentState(
        user_input=user_input,
        agent_response="",
        messages=conversation_memory,
        intent_result={},
        memory_context="",
        tool_name="",
        tool_args={},
        tool_output="",
        tool_success=False,
        needs_confirmation=False,
        confirmed=False,
        pending_tool=pending_tool,
        session_id=SESSION_ID,
        turn_number=len(conversation_memory) // 2,
        error_message="",
        _routing_action="",
    )
    
    result = agent.invoke(state)
    conversation_memory = result.get("messages", [])
    
    print(f"\n{'='*60}")
    print(f"You: {user_input}")
    print(f"Messages in memory: {len(conversation_memory)}")
    
    # Show recent history
    if conversation_memory:
        print("\nConversation history:")
        for msg in conversation_memory[-6:]:
            role = "User" if msg.type == "human" else "Agent"
            content = msg.content[:80]
            print(f"  {role}: {content}")
    
    intent = result.get("intent_result", {})
    print(f"\nIntent: {intent.get('intent')}")
    print(f"Tool: {intent.get('tool_name')}")
    print(f"Confidence: {intent.get('confidence', 0):.2f}")
    
    response = result.get("agent_response", "")
    print(f"\nWPA: {response}")
    
    return response

if __name__ == "__main__":
    # Test 1: Context reference
    print("\n" + "="*60)
    print("TEST 1: Context reference (Spotify)")
    print("="*60)
    
    test_agent("Why do we use Spotify?")
    test_agent("Can you open that?")
    
    # Reset for next test
    conversation_memory = []
    
    print("\n" + "="*60)
    print("TEST 2: Context reference (Chrome)")
    print("="*60)
    
    test_agent("Tell me about Google Chrome")
    test_agent("Open it please")
