#!/usr/bin/env python
"""
ChromaDB Memory Viewer - Displays all content stored in WPA's ChromaDB semantic memory.
Run: python tests/view_chroma_memory.py
"""

import sys
import os
from pathlib import Path
from datetime import datetime
import json

# Add project root to path
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, project_root)

from src.wpa.memory.chroma_memory import (
    get_relevant_preferences,
    get_relevant_history,
    build_context_block,
    count_stored,
    get_all_preferences,
    CHROMA_PATH,
    _init,
    _prefs_collection,
    _history_collection
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
    """Check if ChromaDB database exists."""
    print_header("📁 ChromaDB Information")
    
    chroma_path = Path(CHROMA_PATH)
    print(f"\nDatabase Path: {chroma_path}")
    print(f"Absolute Path: {chroma_path.resolve()}")
    
    if chroma_path.exists():
        # Check if chroma.sqlite3 exists
        sqlite_file = chroma_path / "chroma.sqlite3"
        if sqlite_file.exists():
            size = sqlite_file.stat().st_size
            size_kb = size / 1024
            modified = datetime.fromtimestamp(sqlite_file.stat().st_mtime)
            
            print(f"Status: ✅ EXISTS")
            print(f"Size: {size_kb:.2f} KB ({size:,} bytes)")
            print(f"Last Modified: {modified.strftime('%Y-%m-%d %H:%M:%S')}")
            
            # Count stored documents
            _init()
            counts = count_stored()
            print(f"\nStored Documents:")
            print(f"  • Preferences: {counts['preferences']}")
            print(f"  • History: {counts['history']}")
            print(f"  • Total: {counts['preferences'] + counts['history']}")
            
            return True
        else:
            print(f"Status: ⚠️  Directory exists but database not found")
            return False
    else:
        print(f"Status: ❌ NOT FOUND")
        print("\nThe database will be created when you first run WPA.")
        return False


def view_all_preferences():
    """View all stored preferences."""
    print_section("⚙️  All User Preferences")
    
    try:
        _init()
        
        # Access the global collection after init
        from src.wpa.memory.chroma_memory import _prefs_collection as prefs
        
        if prefs is None:
            print("\n❌ Failed to initialize ChromaDB.")
            return
        
        results = prefs.get(
            include=["documents", "metadatas"]
        )
        
        docs = results.get("documents", [])
        metas = results.get("metadatas", [])
        ids = results.get("ids", [])
        
        if not docs:
            print("\n❌ No preferences stored.")
            print("   Say things like 'Remember I prefer volume at 40%'")
            return
        
        print(f"\nTotal preferences: {len(docs)}\n")
        
        for i, (doc_id, doc, meta) in enumerate(zip(ids, docs, metas), 1):
            timestamp = meta.get('timestamp', 'N/A')
            if timestamp != 'N/A':
                timestamp = timestamp.replace('T', ' ')[:19]
            
            print(f"[{i}] {doc}")
            print(f"    ID: {doc_id}")
            print(f"    Stored: {timestamp}")
            print()
        
    except Exception as e:
        print(f"\n❌ Error: {e}")
        import traceback
        traceback.print_exc()


def view_all_history():
    """View all stored interaction summaries."""
    print_section("📜 All Interaction History")
    
    try:
        _init()
        
        # Access the global collection after init
        from src.wpa.memory.chroma_memory import _history_collection as history
        
        if history is None:
            print("\n❌ Failed to initialize ChromaDB.")
            return
        
        results = history.get(
            include=["documents", "metadatas"]
        )
        
        docs = results.get("documents", [])
        metas = results.get("metadatas", [])
        ids = results.get("ids", [])
        
        if not docs:
            print("\n❌ No interaction history stored.")
            print("   Use WPA to perform actions and build up history!")
            return
        
        print(f"\nTotal interactions: {len(docs)}\n")
        
        for i, (doc_id, doc, meta) in enumerate(zip(ids, docs, metas), 1):
            timestamp = meta.get('timestamp', 'N/A')
            if timestamp != 'N/A':
                timestamp = timestamp.replace('T', ' ')[:19]
            
            session_id = meta.get('session_id', 'N/A')
            tool_name = meta.get('tool_name', 'N/A')
            user_input = meta.get('user_input', 'N/A')
            
            print(f"[{i}] {timestamp}")
            print(f"    Session: {session_id}")
            print(f"    Tool: {tool_name}")
            print(f"    User Input: \"{user_input}\"")
            print(f"    Summary: {doc}")
            print(f"    ID: {doc_id}")
            print()
        
    except Exception as e:
        print(f"\n❌ Error: {e}")
        import traceback
        traceback.print_exc()


def semantic_search_preferences():
    """Semantic search through preferences."""
    print_section("🔍 Semantic Search - Preferences")
    
    query = input("\nEnter search query: ").strip()
    
    if not query:
        print("❌ No query provided.")
        return
    
    try:
        n_results = input("How many results? (default 5): ").strip()
        n_results = int(n_results) if n_results.isdigit() else 5
        
        _init()
        from src.wpa.memory.chroma_memory import _prefs_collection as prefs
        
        if prefs is None or prefs.count() == 0:
            print(f"\n❌ No preferences found.")
            return
        
        results = prefs.query(
            query_texts=[query],
            n_results=min(n_results, prefs.count()),
            include=["documents", "metadatas", "distances"]
        )
        
        docs = results.get("documents", [[]])[0]
        metas = results.get("metadatas", [[]])[0]
        distances = results.get("distances", [[]])[0]
        
        if not docs:
            print(f"\n❌ No preferences found for '{query}'")
            return
        
        print(f"\n✅ Found {len(docs)} results for '{query}':\n")
        
        for i, (doc, meta, dist) in enumerate(zip(docs, metas, distances), 1):
            timestamp = meta.get('timestamp', 'N/A')
            if timestamp != 'N/A':
                timestamp = timestamp.replace('T', ' ')[:19]
            
            # Lower distance = more similar
            similarity = max(0, 1 - dist)
            
            print(f"[{i}] Similarity: {similarity:.2%} (distance: {dist:.4f})")
            print(f"    Preference: {doc}")
            print(f"    Stored: {timestamp}")
            print()
        
    except Exception as e:
        print(f"\n❌ Error: {e}")
        import traceback
        traceback.print_exc()


def semantic_search_history():
    """Semantic search through history."""
    print_section("🔍 Semantic Search - History")
    
    query = input("\nEnter search query: ").strip()
    
    if not query:
        print("❌ No query provided.")
        return
    
    try:
        n_results = input("How many results? (default 5): ").strip()
        n_results = int(n_results) if n_results.isdigit() else 5
        
        _init()
        from src.wpa.memory.chroma_memory import _history_collection as history
        
        if history is None or history.count() == 0:
            print(f"\n❌ No history found.")
            return
        
        results = history.query(
            query_texts=[query],
            n_results=min(n_results, history.count()),
            include=["documents", "metadatas", "distances"]
        )
        
        docs = results.get("documents", [[]])[0]
        metas = results.get("metadatas", [[]])[0]
        distances = results.get("distances", [[]])[0]
        
        if not docs:
            print(f"\n❌ No history found for '{query}'")
            return
        
        print(f"\n✅ Found {len(docs)} results for '{query}':\n")
        
        for i, (doc, meta, dist) in enumerate(zip(docs, metas, distances), 1):
            timestamp = meta.get('timestamp', 'N/A')
            if timestamp != 'N/A':
                timestamp = timestamp.replace('T', ' ')[:19]
            
            tool_name = meta.get('tool_name', 'N/A')
            user_input = meta.get('user_input', 'N/A')
            
            # Lower distance = more similar
            similarity = max(0, 1 - dist)
            
            print(f"[{i}] Similarity: {similarity:.2%} (distance: {dist:.4f})")
            print(f"    Time: {timestamp}")
            print(f"    Tool: {tool_name}")
            print(f"    User Input: \"{user_input}\"")
            print(f"    Summary: {doc}")
            print()
        
    except Exception as e:
        print(f"\n❌ Error: {e}")
        import traceback
        traceback.print_exc()


def view_context_block():
    """View what context block is generated for a query."""
    print_section("🧠 Context Block Generator")
    
    query = input("\nEnter query to generate context for: ").strip()
    
    if not query:
        print("❌ No query provided.")
        return
    
    try:
        print(f"\nGenerating context block for: '{query}'\n")
        print("─" * 80)
        
        context = build_context_block(query)
        
        if not context:
            print("❌ No relevant context found.")
            print("   This happens when no preferences or history match the query.")
            return
        
        print("\n" + context)
        print("\n" + "─" * 80)
        print("\n💡 This context is injected into LLM prompts to provide memory.\n")
        
    except Exception as e:
        print(f"\n❌ Error: {e}")


def view_collection_stats():
    """View detailed statistics about collections."""
    print_section("📊 Collection Statistics")
    
    try:
        _init()
        from src.wpa.memory.chroma_memory import _prefs_collection as prefs, _history_collection as history
        
        if prefs is None or history is None:
            print("\n❌ Failed to initialize ChromaDB.")
            return
        
        # Preferences stats
        prefs_count = prefs.count()
        print(f"\n📁 User Preferences Collection:")
        print(f"   • Name: {prefs.name}")
        print(f"   • Documents: {prefs_count}")
        print(f"   • Metadata: {prefs.metadata}")
        
        if prefs_count > 0:
            # Get a sample
            sample = prefs.get(limit=1, include=["embeddings"])
            if sample and sample.get("embeddings"):
                embedding_dim = len(sample["embeddings"][0])
                print(f"   • Embedding Dimension: {embedding_dim}")
        
        # History stats
        history_count = history.count()
        print(f"\n📜 Interaction History Collection:")
        print(f"   • Name: {history.name}")
        print(f"   • Documents: {history_count}")
        print(f"   • Metadata: {history.metadata}")
        
        if history_count > 0:
            # Get a sample
            sample = history.get(limit=1, include=["embeddings"])
            if sample and sample.get("embeddings"):
                embedding_dim = len(sample["embeddings"][0])
                print(f"   • Embedding Dimension: {embedding_dim}")
        
        print(f"\n📊 Total Documents: {prefs_count + history_count}")
        
        # Estimate storage size
        chroma_path = Path(CHROMA_PATH)
        total_size = 0
        if chroma_path.exists():
            for file in chroma_path.rglob("*"):
                if file.is_file():
                    total_size += file.stat().st_size
        
        print(f"💾 Total Storage: {total_size / 1024:.2f} KB ({total_size:,} bytes)")
        
    except Exception as e:
        print(f"\n❌ Error: {e}")
        import traceback
        traceback.print_exc()


def export_to_json():
    """Export all ChromaDB data to JSON."""
    print_section("💾 Export to JSON")
    
    try:
        _init()
        from src.wpa.memory.chroma_memory import _prefs_collection as prefs, _history_collection as history
        
        if prefs is None or history is None:
            print("\n❌ Failed to initialize ChromaDB.")
            return
        
        # Get all preferences
        prefs_results = prefs.get(
            include=["documents", "metadatas"]
        )
        
        # Get all history
        history_results = history.get(
            include=["documents", "metadatas"]
        )
        
        data = {
            "exported_at": datetime.now().isoformat(),
            "embedding_model": "all-MiniLM-L6-v2",
            "preferences": {
                "count": len(prefs_results.get("documents", [])),
                "items": [
                    {
                        "id": doc_id,
                        "document": doc,
                        "metadata": meta
                    }
                    for doc_id, doc, meta in zip(
                        prefs_results.get("ids", []),
                        prefs_results.get("documents", []),
                        prefs_results.get("metadatas", [])
                    )
                ]
            },
            "history": {
                "count": len(history_results.get("documents", [])),
                "items": [
                    {
                        "id": doc_id,
                        "document": doc,
                        "metadata": meta
                    }
                    for doc_id, doc, meta in zip(
                        history_results.get("ids", []),
                        history_results.get("documents", []),
                        history_results.get("metadatas", [])
                    )
                ]
            }
        }
        
        output_file = "chroma_memory_export.json"
        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        
        print(f"\n✅ Exported to: {output_file}")
        print(f"   Preferences: {data['preferences']['count']}")
        print(f"   History: {data['history']['count']}")
        print(f"   Total: {data['preferences']['count'] + data['history']['count']}")
        
    except Exception as e:
        print(f"\n❌ Export failed: {e}")
        import traceback
        traceback.print_exc()


def clear_memory_warning():
    """Clear all ChromaDB memory (with confirmation)."""
    print_section("⚠️  Clear Memory")
    
    print("\n⚠️  WARNING: This will delete ALL stored semantic memory!")
    print("   - All user preferences")
    print("   - All interaction history")
    print("   - All vector embeddings")
    
    confirm = input("\nType 'DELETE ALL' to confirm: ").strip()
    
    if confirm == "DELETE ALL":
        try:
            _init()
            from src.wpa.memory.chroma_memory import _prefs_collection as prefs, _history_collection as history
            
            if prefs is None or history is None:
                print("\n❌ Failed to initialize ChromaDB.")
                return
            
            # Delete all documents from both collections
            prefs_ids = prefs.get()["ids"]
            if prefs_ids:
                prefs.delete(ids=prefs_ids)
            
            history_ids = history.get()["ids"]
            if history_ids:
                history.delete(ids=history_ids)
            
            print(f"\n✅ Memory cleared successfully.")
            print(f"   Deleted {len(prefs_ids)} preferences")
            print(f"   Deleted {len(history_ids)} history items")
        except Exception as e:
            print(f"\n❌ Failed to clear memory: {e}")
            import traceback
            traceback.print_exc()
    else:
        print("\n❌ Cancelled. Memory not cleared.")


def show_menu():
    """Display main menu."""
    print_header("🗄️  ChromaDB Memory Viewer")
    
    print("\nChoose an option:\n")
    print("  1️⃣  View All Preferences")
    print("  2️⃣  View All History")
    print("  3️⃣  Semantic Search - Preferences")
    print("  4️⃣  Semantic Search - History")
    print("  5️⃣  View Context Block Generator")
    print("  6️⃣  View Collection Statistics")
    print("  7️⃣  Export to JSON")
    print("  8️⃣  Clear All Memory (⚠️ Dangerous)")
    print("  0️⃣  Exit\n")


def main():
    """Main menu loop."""
    
    # Check if database exists
    if not check_database_exists():
        print("\n💡 Tip: Run WPA first to create the database and start building memory.")
        response = input("\nContinue anyway? (y/n): ").strip().lower()
        if response != 'y':
            return
    
    while True:
        show_menu()
        
        choice = input("Enter choice (0-8): ").strip()
        
        if choice == "1":
            view_all_preferences()
        
        elif choice == "2":
            view_all_history()
        
        elif choice == "3":
            semantic_search_preferences()
        
        elif choice == "4":
            semantic_search_history()
        
        elif choice == "5":
            view_context_block()
        
        elif choice == "6":
            view_collection_stats()
        
        elif choice == "7":
            export_to_json()
        
        elif choice == "8":
            clear_memory_warning()
        
        elif choice == "0":
            print("\n👋 Exiting...\n")
            break
        
        else:
            print("❌ Invalid choice. Please enter 0-8.\n")
        
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
