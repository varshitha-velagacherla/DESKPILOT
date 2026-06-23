"""sqlite_memory.py  —  Episodic Memory

Stores every interaction permanently in SQLite.
No LLM, no embeddings — just plain SQL.

Called by memory_node at the end of every turn.
"""

import sqlite3
import json
import logging

from datetime import datetime
from pathlib import Path
from typing import List, Dict, Optional


logger = logging.getLogger("wpa.memory.sqlite")


# ── Database location ─────────────────────────────────────────────────────────

DB_PATH = Path("memory/wpa_memory.db")


def _get_conn() -> sqlite3.Connection:
    """Get a database connection. Creates DB and tables if not exist."""

    DB_PATH.parent.mkdir(
        parents=True,
        exist_ok=True
    )

    conn = sqlite3.connect(str(DB_PATH))

    conn.row_factory = sqlite3.Row

    _create_tables(conn)

    return conn


def _create_tables(conn: sqlite3.Connection):

    """Create tables if they don't exist yet."""

    conn.executescript("""

        CREATE TABLE IF NOT EXISTS interactions (

            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id  TEXT    NOT NULL,
            timestamp   TEXT    NOT NULL,
            user_input  TEXT    NOT NULL,
            intent      TEXT    DEFAULT '',
            tool_name   TEXT    DEFAULT '',
            tool_args   TEXT    DEFAULT '{}',
            tool_output TEXT    DEFAULT '',
            success     INTEGER DEFAULT 0,
            response    TEXT    DEFAULT ''

        );



        CREATE TABLE IF NOT EXISTS preferences (

            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            key         TEXT    NOT NULL UNIQUE,
            value       TEXT    NOT NULL,
            updated_at  TEXT    NOT NULL

        );



        CREATE INDEX IF NOT EXISTS idx_interactions_session
            ON interactions(session_id);



        CREATE INDEX IF NOT EXISTS idx_interactions_tool
            ON interactions(tool_name);



        CREATE INDEX IF NOT EXISTS idx_interactions_timestamp
            ON interactions(timestamp);

    """)

    conn.commit()


# ══════════════════════════════════════════════════════════════════════════════
# WRITE
# ══════════════════════════════════════════════════════════════════════════════

def save_interaction(

    session_id:  str,
    user_input:  str,
    intent:      str  = "",
    tool_name:   str  = "",
    tool_args:   dict = None,
    tool_output: str  = "",
    success:     bool = False,
    response:    str  = "",

) -> int:

    """
    Save one interaction turn to SQLite.

    Prevents noisy/duplicate storage caused by:
        - whitespace changes
        - casing differences
        - repeated identical turns

    Returns:
        row id if inserted
        existing row id if duplicate
        -1 on failure
    """

    tool_args = tool_args or {}

    conn = None

    try:

        conn = _get_conn()


        # ── Normalize fields ──────────────────────────────────────────────────

        user_input = (
            user_input
            .strip()
        )

        intent = (
            intent
            .strip()
            .lower()
        )

        tool_name = (
            tool_name
            .strip()
            .lower()
        )

        tool_output = (
            tool_output
            .strip()
        )

        response = (
            response
            .strip()
        )


        # Normalize tool args for stable comparison

        tool_args_json = json.dumps(

            tool_args,

            sort_keys=True
        )


        # ── Duplicate detection ───────────────────────────────────────────────

        existing = conn.execute(

            """
            SELECT id
            FROM interactions

            WHERE

                user_input  = ?
                AND intent  = ?
                AND tool_name = ?
                AND tool_args = ?
                AND response = ?

            ORDER BY id DESC
            LIMIT 1
            """,

            (
                user_input,
                intent,
                tool_name,
                tool_args_json,
                response,
            )
        ).fetchone()


        # If same interaction already exists, skip insert

        if existing:

            existing_id = existing["id"]

            # logger.info(
            #     f"[sqlite] duplicate interaction skipped id={existing_id}"
            # )

            return existing_id


        # ── Insert new interaction ────────────────────────────────────────────

        timestamp = datetime.now().isoformat()


        cursor = conn.execute(

            """
            INSERT INTO interactions

                (
                    session_id,
                    timestamp,
                    user_input,
                    intent,
                    tool_name,
                    tool_args,
                    tool_output,
                    success,
                    response
                )

            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,

            (
                session_id,
                timestamp,
                user_input,
                intent,
                tool_name,
                tool_args_json,
                tool_output,
                int(success),
                response,
            )
        )


        conn.commit()

        row_id = cursor.lastrowid


        # logger.info(
        #     f"[sqlite] saved interaction id={row_id} tool={tool_name}"
        # )


        return row_id


    except Exception as e:

        logger.error(
            f"[sqlite] save_interaction failed: {e}"
        )

        return -1


    finally:

        if conn:
            conn.close()

def save_preference(key: str, value: str):

    """
    Save or update a user preference.

    Prevents duplicates by normalizing key/value.

    Example:
        save_preference("preferred_volume", "40")
    """

    conn = None

    try:

        conn = _get_conn()


        # ── Normalize ────────────────────────────────────────────────────────

        key = (

            key
            .strip()
            .lower()
        )

        value = (
            value
            .strip()
        )


        # Skip empty values

        if not key or not value:

            logger.warning(
                "[sqlite] skipped empty preference"
            )

            return


        conn.execute(

            """
            INSERT INTO preferences
                (key, value, updated_at)

            VALUES (?, ?, ?)

            ON CONFLICT(key)
            DO UPDATE SET

                value      = excluded.value,
                updated_at = excluded.updated_at
            """,

            (
                key,
                value,
                datetime.now().isoformat()
            )
        )

        conn.commit()

        # logger.info(
        #     f"[sqlite] saved preference {key}={value}"
        # )

    except Exception as e:

        logger.error(
            f"[sqlite] save_preference failed: {e}"
        )

    finally:

        if conn:
            conn.close()

# ══════════════════════════════════════════════════════════════════════════════
# READ
# ══════════════════════════════════════════════════════════════════════════════

def get_recent_interactions(
    limit: int = 10
) -> List[Dict]:

    """Get latest N interactions."""

    conn = None

    try:

        conn = _get_conn()

        rows = conn.execute(

            """
            SELECT *
            FROM interactions
            ORDER BY timestamp DESC
            LIMIT ?
            """,

            (limit,)
        ).fetchall()

        return [dict(r) for r in rows]

    except Exception as e:

        logger.error(
            f"[sqlite] get_recent_interactions failed: {e}"
        )

        return []

    finally:

        if conn:
            conn.close()


def get_session_interactions(
    session_id: str
) -> List[Dict]:

    """Get all interactions for a specific session."""

    conn = None

    try:

        conn = _get_conn()

        rows = conn.execute(

            """
            SELECT *
            FROM interactions
            WHERE session_id = ?
            ORDER BY timestamp ASC
            """,

            (session_id,)
        ).fetchall()

        return [dict(r) for r in rows]

    except Exception as e:

        logger.error(
            f"[sqlite] get_session_interactions failed: {e}"
        )

        return []

    finally:

        if conn:
            conn.close()


def get_tool_usage_stats() -> List[Dict]:

    """
    Get tool usage statistics.

    Useful for:
        "What tools do I use most?"
    """

    conn = None

    try:

        conn = _get_conn()

        rows = conn.execute(

            """
            SELECT

                tool_name,

                COUNT(*)       AS total_calls,

                SUM(success)   AS successful_calls,

                MAX(timestamp) AS last_used

            FROM interactions

            WHERE tool_name != ''

            GROUP BY tool_name

            ORDER BY total_calls DESC
            """

        ).fetchall()

        return [dict(r) for r in rows]

    except Exception as e:

        logger.error(
            f"[sqlite] get_tool_usage_stats failed: {e}"
        )

        return []

    finally:

        if conn:
            conn.close()


def search_interactions(
    query: str,
    limit: int = 5
) -> List[Dict]:

    """
    Search interactions using LIKE matching.
    """

    conn = None

    try:

        conn = _get_conn()

        pattern = f"%{query}%"

        rows = conn.execute(

            """
            SELECT *
            FROM interactions

            WHERE

                user_input LIKE ?
                OR tool_name LIKE ?
                OR response LIKE ?

            ORDER BY timestamp DESC

            LIMIT ?
            """,

            (
                pattern,
                pattern,
                pattern,
                limit
            )
        ).fetchall()

        return [dict(r) for r in rows]

    except Exception as e:

        logger.error(
            f"[sqlite] search_interactions failed: {e}"
        )

        return []

    finally:

        if conn:
            conn.close()


def get_preference(
    key: str
) -> Optional[str]:

    """Get stored preference by key."""

    conn = None

    try:

        conn = _get_conn()

        row = conn.execute(

            """
            SELECT value
            FROM preferences
            WHERE key = ?
            """,

            (key,)
        ).fetchone()

        if row:
            return row["value"]

        return None

    except Exception as e:

        logger.error(
            f"[sqlite] get_preference failed: {e}"
        )

        return None

    finally:

        if conn:
            conn.close()


def get_all_preferences() -> Dict[str, str]:

    """Get all stored preferences."""

    conn = None

    try:

        conn = _get_conn()

        rows = conn.execute(

            """
            SELECT key, value
            FROM preferences
            """

        ).fetchall()

        return {

            row["key"]: row["value"]

            for row in rows
        }

    except Exception as e:

        logger.error(
            f"[sqlite] get_all_preferences failed: {e}"
        )

        return {}

    finally:

        if conn:
            conn.close()


def get_memory_summary() -> str:

    """
    Build a lightweight memory summary
    for injecting into prompts.
    """

    try:

        recent      = get_recent_interactions(5)

        stats       = get_tool_usage_stats()

        preferences = get_all_preferences()

        lines = []


        # ── Preferences ───────────────────────────────────────────────────────

        if preferences:

            lines.append(
                "User preferences:"
            )

            for k, v in preferences.items():

                lines.append(
                    f"  - {k}: {v}"
                )


        # ── Tool usage ────────────────────────────────────────────────────────

        if stats:

            top = stats[:3]

            tool_text = ", ".join(

                f"{r['tool_name']} ({r['total_calls']}x)"

                for r in top
            )

            lines.append(
                f"Most used tools: {tool_text}"
            )


        # ── Recent interactions ───────────────────────────────────────────────

        if recent:

            lines.append(
                "Recent interactions:"
            )

            for r in recent[:3]:

                ts = (

                    r["timestamp"]

                    [:16]

                    .replace("T", " ")
                )

                line = (

                    f"  [{ts}] "

                    f"'{r['user_input']}'"
                )

                if r["tool_name"]:

                    line += f" → {r['tool_name']}"

                lines.append(line)


        return "\n".join(lines)

    except Exception as e:

        logger.error(
            f"[sqlite] get_memory_summary failed: {e}"
        )

        return ""