
import sys
sys.path.insert(0, 'src')
from pathlib import Path
Path('memory').mkdir(exist_ok=True)

from wpa.memory.chroma_memory import (
    save_preference, get_relevant_preferences,
    save_interaction_summary, get_relevant_history,
    build_context_block, count_stored
)

# Save preferences
save_preference('User prefers volume at 40 percent')
save_preference('User frequently opens VS Code for coding')
save_preference('User downloads folder is at C:/Users/venkatesh buddhi/Downloads')
save_preference('User prefers dark mode applications')

# Save interaction summaries
save_interaction_summary('s1', 'open notepad', 'open_app', 'Notepad is open.')
save_interaction_summary('s1', 'set volume to 40', 'set_volume', 'Volume set to 40%.')
save_interaction_summary('s1', 'take a screenshot', 'take_screenshot', 'Screenshot saved.')

print('--- Stored counts ---')
print(count_stored())

print('\n--- Relevant preferences for: set the volume ---')
for p in get_relevant_preferences('set the volume', n_results=2):
    print(f'  {p}')

print('\n--- Relevant history for: open an app ---')
for h in get_relevant_history('open an app', n_results=2):
    print(f"  {h[:100]}")
print('\n--- Full context block for: adjust volume ---')
print(build_context_block('adjust volume'))