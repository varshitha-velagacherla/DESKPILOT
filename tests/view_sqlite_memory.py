#!/usr/bin/env python
"""
SQLite Memory Viewer - Displays all content stored in WPA's SQLite memory.
Run: python tests/view_sqlite_memory.py
"""

import sys
import os
from pathlib import Path
from datetime import datetime
import json

# Add project root to path
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, project_root)

from src.wpa.memory.sqlite_memory import (
    get_recent_interactions,
    get_session_interactions,
    get_tool_usage_stats,
    get_all_preferences,
    get_memory_summary,
    search_interactions,
    DB_PATH
)


def print_header(title):
    """Print a formatted header."""
    print("\n" + "=" * 80)
    print(f"  {title}")
    print("=" * 80)


def print_section(title):
    """Print a section separator."""
    print(f"\n{'─' * 80}")
    print(f"  {title}")
    print(f"{'─' * 80}")


def check_database_exists():
    """Check if database file exists."""
    print_header("📁 Database Information")
    
    print(f"\nDatabase Path: {DB_PATH}")
    print(f"Absolute Path: {DB_PATH.resolve()}")
    
    if DB_PATH.exists():
        size = DB_PATH.stat().st_size
        size_kb = size / 1024
        modified = datetime.fromtimestamp(DB_PATH.stat().st_mtime)
        
        print(f"Status: ✅ EXISTS")
        print(f"Size: {size_kb:.2f} KB ({size:,} bytes)")
        print(f"Last Modified: {modified.strftime('%Y-%m-%d %H:%M:%S')}")
        return True
    else:
        print(f"Status: ❌ NOT FOUND")
        print("\nThe database will be created when you first run WPA.")
        return False


def view_all_interactions(limit=None):
    """View all interactions."""
    print_section("💬 All Interactions")
    
    interactions = get_recent_interactions(limit or 1000)
    
    if not interactions:
        print("\n❌ No interactions found in database.")
        print("   Start using WPA to build up memory!")
        return
    
    print(f"\nTotal interactions: {len(interactions)}")
    print()
    
    for i, item in enumerate(reversed(interactions), 1):
        timestamp = item['timestamp'].replace('T', ' ')[:19]
        
        print(f"[{i}] {timestamp}")
        print(f"    Session: {item['session_id'][:8]}...")
        print(f"    User:    \"{item['user_input']}\"")
        
        if item['intent']:
            print(f"    Intent:  {item['intent']}")
        
        if item['tool_name']:
            args = json.loads(item['tool_args']) if item['tool_args'] else {}
            status = "✅" if item['success'] else "❌"
            print(f"    Tool:    {status} {item['tool_name']}")
            if args:
                print(f"    Args:    {args}")
            if item['tool_output']:
                output = item['tool_output'][:100]
                if len(item['tool_output']) > 100:
                    output += "..."
                print(f"    Output:  {output}")
        
        if item['response']:
            response = item['response'][:150]
            if len(item['response']) > 150:
                response += "..."
            print(f"    Response: \"{response}\"")
        
        print()


def view_by_session():
    """View interactions grouped by session."""
    print_section("📅 Interactions by Session")
    
    all_interactions = get_recent_interactions(1000)
    
    if not all_interactions:
        print("\n❌ No interactions found.")
        return
    
    # Group by session
    sessions = {}
    for item in all_interactions:
        sid = item['session_id']
        if sid not in sessions:
            sessions[sid] = []
        sessions[sid].append(item)
    
    print(f"\nTotal sessions: {len(sessions)}\n")
    
    for sid, items in sorted(sessions.items(), key=lambda x: x[1][0]['timestamp'], reverse=True):
        first = items[0]
        last = items[-1]
        
        start_time = first['timestamp'].replace('T', ' ')[:19]
        end_time = last['timestamp'].replace('T', ' ')[:19]
        
        print(f"Session: {sid}")
        print(f"  Start:        {start_time}")
        print(f"  End:          {end_time}")
        print(f"  Interactions: {len(items)}")
        print(f"  Tools used:   {len([i for i in items if i['tool_name']])}")
        print()


def view_tool_statistics():
    """View tool usage statistics."""
    print_section("🔧 Tool Usage Statistics")
    
    stats = get_tool_usage_stats()
    
    if not stats:
        print("\n❌ No tool usage recorded yet.")
        return
    
    print(f"\nTotal unique tools: {len(stats)}\n")
    
    print(f"{'Tool Name':<25} {'Total':<8} {'Success':<8} {'Success Rate':<12} {'Last Used'}")
    print("─" * 80)
    
    for item in stats:
        tool = item['tool_name']
        total = item['total_calls']
        success = item['successful_calls']
        rate = (success / total * 100) if total > 0 else 0
        last = item['last_used'].replace('T', ' ')[:19]
        
        print(f"{tool:<25} {total:<8} {success:<8} {rate:>6.1f}%       {last}")


def view_preferences():
    """View stored preferences."""
    print_section("⚙️  User Preferences")
    
    prefs = get_all_preferences()
    
    if not prefs:
        print("\n❌ No preferences stored.")
        print("   Say things like 'Remember I prefer volume at 40%'")
        return
    
    print(f"\nTotal preferences: {len(prefs)}\n")
    
    for key, value in prefs.items():
        print(f"  {key:<30} = {value}")


def view_memory_summary():
    """View memory summary (what gets injected into LLM)."""
    print_section("🧠 Memory Summary (LLM Context)")
    
    summary = get_memory_summary()
    
    if not summary:
        print("\n❌ No memory summary available.")
        return
    
    print("\nThis is what gets injected into the LLM prompt:\n")
    print(summary)


def search_memory():
    """Interactive search through memory."""
    print_section("🔍 Search Memory")
    
    query = input("\nEnter search term: ").strip()
    
    if not query:
        print("❌ No search term provided.")
        return
    
    results = search_interactions(query, limit=20)
    
    if not results:
        print(f"\n❌ No results found for '{query}'")
        return
    
    print(f"\n✅ Found {len(results)} results for '{query}':\n")
    
    for i, item in enumerate(results, 1):
        timestamp = item['timestamp'].replace('T', ' ')[:19]
        print(f"[{i}] {timestamp}")
        print(f"    User: \"{item['user_input']}\"")
        if item['tool_name']:
            print(f"    Tool: {item['tool_name']}")
        if item['response']:
            response = item['response'][:100]
            if len(item['response']) > 100:
                response += "..."
            print(f"    Response: \"{response}\"")
        print()


def export_to_json():
    """Export all data to JSON file."""
    print_section("💾 Export to JSON")
    
    try:
        data = {
            "exported_at": datetime.now().isoformat(),
            "interactions": get_recent_interactions(10000),
            "tool_stats": get_tool_usage_stats(),
            "preferences": get_all_preferences()
        }
        
        output_file = "memory_export.json"
        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        
        print(f"\n✅ Exported to: {output_file}")
        print(f"   Interactions: {len(data['interactions'])}")
        print(f"   Tools: {len(data['tool_stats'])}")
        print(f"   Preferences: {len(data['preferences'])}")
        
    except Exception as e:
        print(f"\n❌ Export failed: {e}")


def clear_memory_warning():
    """Clear all memory (with confirmation)."""
    print_section("⚠️  Clear Memory")
    
    print("\n⚠️  WARNING: This will delete ALL stored memory!")
    print("   - All interactions")
    print("   - All preferences")
    print("   - All tool usage history")
    
    confirm = input("\nType 'DELETE ALL' to confirm: ").strip()
    
    if confirm == "DELETE ALL":
        try:
            import sqlite3
            conn = sqlite3.connect(str(DB_PATH))
            conn.execute("DELETE FROM interactions")
            conn.execute("DELETE FROM preferences")
            conn.commit()
            conn.close()
            
            print("\n✅ Memory cleared successfully.")
        except Exception as e:
            print(f"\n❌ Failed to clear memory: {e}")
    else:
        print("\n❌ Cancelled. Memory not cleared.")


def show_menu():
    """Display main menu."""
    print_header("🗄️  SQLite Memory Viewer")
    
    print("\nChoose an option:\n")
    print("  1️⃣  View All Interactions")
    print("  2️⃣  View Interactions by Session")
    print("  3️⃣  View Tool Usage Statistics")
    print("  4️⃣  View User Preferences")
    print("  5️⃣  View Memory Summary (LLM Context)")
    print("  6️⃣  Search Memory")
    print("  7️⃣  Export to JSON")
    print("  8️⃣  View Recent (Last 10)")
    print("  9️⃣  Clear All Memory (⚠️ Dangerous)")
    print("  0️⃣  Exit\n")


def main():
    """Main menu loop."""
    
    # Check if database exists
    if not check_database_exists():
        print("\n💡 Tip: Run WPA first to create the database and start building memory.")
        return
    
    while True:
        show_menu()
        
        choice = input("Enter choice (0-9): ").strip()
        
        if choice == "1":
            view_all_interactions()
        
        elif choice == "2":
            view_by_session()
        
        elif choice == "3":
            view_tool_statistics()
        
        elif choice == "4":
            view_preferences()
        
        elif choice == "5":
            view_memory_summary()
        
        elif choice == "6":
            search_memory()
        
        elif choice == "7":
            export_to_json()
        
        elif choice == "8":
            view_all_interactions(limit=10)
        
        elif choice == "9":
            clear_memory_warning()
        
        elif choice == "0":
            print("\n👋 Exiting...\n")
            break
        
        else:
            print("❌ Invalid choice. Please enter 0-9.\n")
        
        input("\nPress Enter to continue...")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\n👋 Interrupted by user.\n")
        sys.exit(0)
    except Exception as e:
        print(f"\n❌ Error: {e}\n")
        import traceback
        traceback.print_exc()
        sys.exit(1)
