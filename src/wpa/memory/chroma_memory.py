
"""
chroma_memory.py  —  Semantic Memory

Stores facts and preferences as vector embeddings.

Enables natural language retrieval:

  "What do you know about me?"
  "Remember that I prefer dark mode"

Uses ChromaDB with local sentence-transformers embeddings.
Fully offline — no API needed.

"""
import os

os.environ["HF_HUB_DISABLE_TELEMETRY"] = "1"
import logging

logging.getLogger(
    "sentence_transformers"
).setLevel(logging.ERROR)

logging.getLogger(
    "huggingface_hub"
).setLevel(logging.ERROR)

logging.getLogger(
    "transformers"
).setLevel(logging.ERROR)

logging.getLogger(
    "httpx"
).setLevel(logging.WARNING)


from datetime import datetime
from typing import List, Dict, Optional
from pathlib import Path


logger = logging.getLogger("wpa.memory.chroma")


CHROMA_PATH        = "memory/chroma_db"

COLLECTION_PREFS   = "user_preferences"

COLLECTION_HISTORY = "interaction_summaries"


# ── Lazy init — don\\'t load heavy models at import time ───────────────────────

_chroma_client      = None
_embedding_fn       = None

_prefs_collection   = None
_history_collection = None


def _init():

    """    
    Initialize ChromaDB and embedding model.
    Called lazily on first use so startup is fast.

    """

    global _chroma_client
    global _embedding_fn
    global _prefs_collection
    global _history_collection


    if _chroma_client is not None:
        return


    try:

        import chromadb

        from chromadb.utils import embedding_functions


        Path(CHROMA_PATH).mkdir(
            parents=True,
            exist_ok=True
        )


        # Persistent client — data survives restarts

        _chroma_client = chromadb.PersistentClient(
            path=CHROMA_PATH
        )


        # Use sentence-transformers for local embeddings (offline)
        # Model downloads once (~90MB), then cached locally

        _embedding_fn = embedding_functions.SentenceTransformerEmbeddingFunction(

            model_name="all-MiniLM-L6-v2"

        )


        # Get or create collections

        _prefs_collection = _chroma_client.get_or_create_collection(

            name="user_preferences",

            embedding_function=_embedding_fn,

            metadata={
                "description": "User preferences and personal facts"
            }
        )


        _history_collection = _chroma_client.get_or_create_collection(

            name="interaction_summaries",

            embedding_function=_embedding_fn,

            metadata={
                "description": "Summaries of past interactions"
            }
        )


        # logger.info(

        #     f"[chroma] initialized | "
        #     f"prefs={_prefs_collection.count()} | "
        #     f"history={_history_collection.count()}"

        # )


    except ImportError as e:

        logger.error(
            f"[chroma] missing dependency: {e}"
        )

        logger.error(
            "Run: pip install chromadb sentence-transformers"
        )

        raise


    except Exception as e:

        logger.error(
            f"[chroma] init failed: {e}"
        )

        raise


# ══════════════════════════════════════════════════════════════════════════════
# WRITE
# ══════════════════════════════════════════════════════════════════════════════

def save_preference(

    preference_text: str,
    pref_id: Optional[str] = None

):

    """
    Save a user preference as a vector embedding.

    Prevents duplicate storage by using
    normalized text as deterministic ID.
    """

    try:

        _init()


        # ── Normalize text for deduplication ─────────────────────────────────

        normalized = (

            preference_text

            .strip()

            .lower()
        )


        # Use provided ID OR deterministic normalized text ID

        doc_id = (

            pref_id or

            normalized
                .replace(" ", "_")
                .replace("/", "_")
                .replace("\\\\", "_")
                [:120]
        )


        _prefs_collection.upsert(

            ids=[doc_id],

            documents=[preference_text],

            metadatas=[{

                "timestamp": datetime.now().isoformat(),

                "type": "preference"

            }]
        )


        # logger.info(
        #     f"[chroma] saved preference: '{preference_text[:60]}'"
        # )


    except Exception as e:

        logger.error(
            f"[chroma] save_preference failed: {e}"
        )


def save_interaction_summary(

    session_id: str,
    user_input: str,
    tool_name:  str,
    response:   str,

):

    """
    Save a summary of an interaction for semantic retrieval.

    Prevents duplicate storage of identical summaries.
    """

    if not tool_name:
        return


    try:

        _init()


        # ── Normalize inputs ──────────────────────────────────────────────────

        user_input = (
            user_input
            .strip()
        )

        tool_name = (
            tool_name
            .strip()
            .lower()
        )

        response = (
            response
            .strip()
        )


        # ── Build summary ────────────────────────────── ──────────────────────

        summary = (

            f"User asked: '{user_input}'. "

            f"Action taken: {tool_name}. "

            f"Result: {response[:150]}"

        )


        # ── Deterministic ID prevents duplicates ─────────────────────────────

        normalized = (

            f"{user_input}_{tool_name}_{response[:80]}"

            .lower()

            .strip()
        )


        doc_id = (

            normalized

            .replace(" ", "_")

            .replace("/", "_")

            .replace("\\\\", "_")

            .replace("'", "")

            [:120]
        )


        # upsert replaces duplicates instead of adding new rows

        _history_collection.upsert(

            ids=[doc_id],

            documents=[summary],

            metadatas=[{

                "session_id": session_id,

                "tool_name": tool_name,

                "timestamp": datetime.now().isoformat(),

                "user_input": user_input[:100],

            }]
        )


        #logger.info(
        #     f"[chroma] saved summary for tool={tool_name}"
        # )


    except Exception as e:

        logger.error(
            f"[chroma] save_interaction_summary failed: {e}"
        )


# ══════════════════════════════════════════════════════════════════════════════
# READ
# ══════════════════════════════════════════════════════════════════════════════

def get_relevant_preferences(

    query: str,
    n_results: int = 3

) -> List[str]:

    """
    Retrieve preferences most relevant to the current query.

    Used to inject context into the LLM before it responds.

    Example:

        query = "set the volume"

        returns:
            ["User prefers volume at 40 percent"]
    """

    try:

        _init()

        if _prefs_collection.count() == 0:
            return []


        results = _prefs_collection.query(

            query_texts=[query],

            n_results=min(
                n_results,
                _prefs_collection.count()
            ),
        )


        docs = results.get(
            "documents",
            [[]]
        )[0]


        # logger.info(
        #     f"[chroma] retrieved {len(docs)} preferences for '{query[:40]}'"
        # )


        return docs


    except Exception as e:

        logger.error(
            f"[chroma] get_relevant_preferences failed: {e}"
        )

        return []
# ══════════════════════════════════════════════════════════════════════════════
# READ
# ══════════════════════════════════════════════════════════════════════════════

def get_relevant_preferences(

    query: str,
    n_results: int = 3

) -> List[str]:

    """
    Retrieve preferences most relevant to the current query.

    Used to inject context into the LLM before it responds.

    Example:

        query = "set the volume"

        returns:
            ["User prefers volume at 40 percent"]
    """

    try:

        _init()

        if _prefs_collection.count() == 0:
            return []


        results = _prefs_collection.query(

            query_texts=[query],

            n_results=min(
                n_results,
                _prefs_collection.count()
            ),
        )


        docs = results.get(
            "documents",
            [[]]
        )[0]


        # logger.info(
        #     f"[chroma] retrieved {len(docs)} preferences for '{query[:40]}'"
        # )


        return docs


    except Exception as e:

        logger.error(
            f"[chroma] get_relevant_preferences failed: {e}"
        )

        return []


def get_relevant_history(

    query: str,
    n_results: int = 3

) -> List[str]:

    """
    Retrieve semantically similar past interaction summaries.

    Example:

        query = "open vscode"

        returns:
            [
                "User asked: 'open vscode'. Action taken: open_app..."
            ]
    """

    try:

        _init()

        if _history_collection.count() == 0:
            return []


        results = _history_collection.query(

            query_texts=[query],

            n_results=min(
                n_results,
                _history_collection.count()
            ),
        )


        docs = results.get(
            "documents",
            [[]]
        )[0]


        # logger.info(
        #     f"[chroma] retrieved {len(docs)} history items for '{query[:40]}'"
        # )


        return docs


    except Exception as e:

        logger.error(
            f"[chroma] get_relevant_history failed: {e}"
        )

        return []


def build_context_block(
    query: str
) -> str:

    """
    Build a compact memory context block
    for injecting into LLM prompts.

    Combines:

        - relevant preferences
        - relevant interaction history
    """

    try:

        prefs = get_relevant_preferences(
            query=query,
            n_results=3
        )

        history = get_relevant_history(
            query=query,
            n_results=3
        )


        lines = []


        # ── Preferences ───────────────────────────────────────────────────────

        if prefs:

            lines.append(
                "Relevant preferences:"
            )

            for p in prefs:

                lines.append(
                    f"  - {p}"
                )


        # ── Relevant history ──────────────────────────────────────────────────

        if history:

            lines.append(
                "Relevant past interactions:"
            )

            for h in history:

                lines.append(
                    f"  - {h}"
                )


        context = "\n".join(lines)


        # logger.info(
        #     f"[chroma] built context block ({len(context)} chars)"
        # )


        return context


    except Exception as e:

        logger.error(
            f"[chroma] build_context_block failed: {e}"
        )

        return ""


def count_stored() -> Dict[str, int]:

    """
    Return how many documents are stored
    in each Chroma collection.

    Useful for debugging/status pages.
    """

    try:

        _init()

        return {

            "preferences":
                _prefs_collection.count(),

            "history":
                _history_collection.count(),
        }


    except Exception as e:

        logger.error(
            f"[chroma] count_stored failed: {e}"
        )

        return {

            "preferences": 0,

            "history": 0,
        }
    
def get_all_preferences() -> List[str]:

    """
    Return all stored preference documents.
    """

    try:

        _init()

        results = _prefs_collection.get()

        docs = results.get(
            "documents",
            []
        )

        return docs

    except Exception as e:

        logger.error(
            f"[chroma] get_all_preferences failed: {e}"
        )

        return []