import sys
sys.path.insert(0, 'src')
from pathlib import Path
Path('memory').mkdir(exist_ok=True)

from wpa.memory.sqlite_memory import (
    save_interaction, get_recent_interactions,
    get_tool_usage_stats, get_memory_summary,
    save_preference, get_preference, search_interactions
)

# Save some test interactions
save_interaction('test_session', 'open notepad',
                 intent='tool_use', tool_name='open_app',
                 tool_args={'app_name':'notepad'},
                 tool_output='Opened notepad successfully.',
                 success=True, response='Notepad is open.')

save_interaction('test_session', 'what time is it',
                 intent='tool_use', tool_name='get_current_time',
                 tool_args={}, tool_output='It is 3:41 PM',
                 success=True, response='It is 3:41 PM.')

save_interaction('test_session', 'hello',
                 intent='chat', response='Hello! I am WPA.')

save_preference('preferred_volume', '40')
save_preference('preferred_browser', 'chrome')

print('--- Recent interactions ---')
for r in get_recent_interactions(3):
    print(f"  [{r['timestamp'][:16]}] '{r['user_input']}' -> {r['tool_name'] or 'chat'}")

print('\n--- Tool usage stats ---')
for s in get_tool_usage_stats():
    print(f"  {s['tool_name']}: {s['total_calls']}x (last: {s['last_used'][:10]})")

print('\n--- Preference lookup ---')
print(f"  preferred_volume = {get_preference('preferred_volume')}")

print('\n--- Search ---')
results = search_interactions('notepad')
for r in results:
    print(f"  Found: '{r['user_input']}'")

print('\n--- Memory summary (injected into LLM) ---')
print(get_memory_summary())