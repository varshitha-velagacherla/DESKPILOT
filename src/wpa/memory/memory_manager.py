"""
memory_manager.py  —  Single Interface for All Memory

Instead of importing sqlite_memory and chroma_memory separately
everywhere, import MemoryManager and use one object.

Usage:

    from wpa.memory.memory_manager import memory

    memory.save_turn(session_id, user_input, ...)
    memory.get_context(user_input)
    memory.remember("User prefers dark mode apps")
"""

import logging

from typing import Dict, List, Optional


from .sqlite_memory import (

    save_interaction,

    save_preference as sqlite_save_pref,

    get_preference,

    get_all_preferences as sqlite_get_all_prefs,

    get_recent_interactions,

    get_tool_usage_stats,

    search_interactions,

    get_memory_summary,

)


logger = logging.getLogger("wpa.memory")


# ChromaDB is optional — if not installed, semantic memory is skipped gracefully

try:

    from .chroma_memory import (

        save_preference as chroma_save_pref,

        save_interaction_summary,

        get_relevant_preferences,

        get_relevant_history,

        build_context_block,

        get_all_preferences as chroma_get_all_prefs,

        count_stored,

    )

    CHROMA_AVAILABLE = True

    # logger.info(
    #     "[memory] ChromaDB available"
    # )

except Exception as e:

    CHROMA_AVAILABLE = False

    logger.warning(
        f"[memory] ChromaDB not available ({e}), using SQLite only"
    )


class MemoryManager:

    """
    Single interface for all memory operations.

    SQLite is always used.
    ChromaDB is used if available.
    """

    # ── WRITE ─────────────────────────────────────────────────────────────────

    def save_turn(

        self,

        session_id:  str,

        user_input:  str,

        intent:      str  = "",

        tool_name:   str  = "",

        tool_args:   dict = None,

        tool_output: str  = "",

        success:     bool = False,

        response:    str  = "",

    ):

        """
        Save a complete interaction turn to memory.
        Called by memory_node at the end of every turn.
        """

        tool_args = tool_args or {}


        # Always save to SQLite

        save_interaction(

            session_id=session_id,

            user_input=user_input,

            intent=intent,

            tool_name=tool_name,

            tool_args=tool_args,

            tool_output=tool_output,

            success=success,

            response=response,

        )


        # Save summary to ChromaDB for semantic retrieval

        if CHROMA_AVAILABLE and tool_name:

            save_interaction_summary(

                session_id=session_id,

                user_input=user_input,

                tool_name=tool_name,

                response=response,

            )


        # logger.info(

        #     f"[memory] saved turn | "
        #     f"intent={intent} "
        #     f"tool={tool_name} "
        #     f"success={success}"

        # )


    def remember(

        self,

        fact: str,

        key: Optional[str] = None

    ):

        """
        Explicitly store a preference or fact.

        Called when user says:
            "remember that..."
            "my downloads folder is..."

        Args:

            fact:
                plain English string to remember

            key:
                optional short key for SQLite
                (e.g. "preferred_volume")
        """


        # Save to SQLite preferences table if key given

        if key:

            sqlite_save_pref(
                key,
                fact
            )


        # Always save to ChromaDB for semantic search

        if CHROMA_AVAILABLE:

            chroma_save_pref(
                fact,
                pref_id=key
            )


        # logger.info(
        #     f"[memory] remembered: '{fact[:80]}'"
        # )


    # ── READ ──────────────────────────────────────────────────────────────────

    def get_context(
        self,
        user_input: str
    ) -> str:

        """
        Build a context block to inject into LLM prompts.

        Combines SQLite summary +
        ChromaDB semantic retrieval.

        Returns empty string if nothing relevant found.
        """

        parts = []


        # SQLite: recent summary

        sqlite_summary = get_memory_summary()

        if sqlite_summary:

            parts.append(
                sqlite_summary
            )


        # ChromaDB: semantically relevant context

        if CHROMA_AVAILABLE:

            chroma_context = build_context_block(
                user_input
            )

            if chroma_context:

                parts.append(
                    chroma_context
                )


        return "\n\n".join(parts) if parts else ""


    def get_preference(
        self,
        key: str
    ) -> Optional[str]:

        """Get a specific stored preference by key."""

        return get_preference(key)


    def get_recent(
        self,
        limit: int = 10
    ) -> List[Dict]:

        """Get N most recent interactions."""

        return get_recent_interactions(limit)


    def get_stats(self) -> List[Dict]:

        """Get tool usage statistics."""

        return get_tool_usage_stats()


    def search(
        self,
        query: str,
        limit: int = 5
    ) -> List[Dict]:

        """Search past interactions by text."""

        return search_interactions(query, limit)


    def status(self) -> Dict:

        """Return memory system status."""

        recent = get_recent_interactions(1)

        stats = {

            "sqlite_available": True,

            "chroma_available": CHROMA_AVAILABLE,

            "total_interactions": len(
                get_recent_interactions(9999)
            ),

            "last_interaction":

                recent[0]["timestamp"][:16]

                if recent else

                "none",
        }


        if CHROMA_AVAILABLE:

            chroma_counts = count_stored()

            stats.update({

                "chroma_preferences":
                    chroma_counts["preferences"],

                "chroma_summaries":
                    chroma_counts["history"],

            })


        return stats


# ── Singleton — import this everywhere ───────────────────────────────────────

memory = MemoryManager()
