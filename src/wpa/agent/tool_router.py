
"""
100% deterministic Python. No LLM involved.
Maps intent_result → which tool to call with which args.
Also enforces confirmation rules.

"""

import logging
from typing import Optional, Tuple

logger = logging.getLogger("wpa.router")

# ── Tools that require user confirmation before running ───────────────────────
RISKY_TOOLS = {
    "delete_file",
    "write_file",
    "close_app",
    "set_volume",
    "set_clipboard",
}

# ── Phrases that mean YES ─────────────────────────────────────────────────────
CONFIRM_PHRASES = {
    "yes", "yeah", "yep", "yup", "sure", "ok", "okay",
    "go ahead", "proceed", "do it", "confirm", "correct",
    "right", "affirmative", "please do", "yes please",
}

# ── Phrases that mean NO ──────────────────────────────────────────────────────
CANCEL_PHRASES = {
    "no", "nope", "nah", "cancel", "stop", "abort",
    "don't", "do not", "never mind", "forget it",
    "skip it", "negative",
}


class ToolRouter:
    """
    Pure Python router. Given an intent_result dict, decides:
    - which tool to run
    - what args to pass
    - whether confirmation is needed first
    - whether to skip (cancel)
    """

    def route(
        self,
        intent_result: dict,
        pending_tool: Optional[dict] = None,
    ) -> Tuple[str, dict, bool]:
        """
        Returns: (action, payload, needs_confirmation)

        action values:
          "execute"     → run tool immediately
          "confirm"     → ask user to confirm before running
          "confirmed"   → user confirmed, now run pending_tool
          "cancelled"   → user cancelled, do nothing
          "chat"        → pass to LLM for conversation
          "clarify"     → ask user to be more specific
          "error"       → something went wrong

        payload: dict with tool_name + tool_args, or {} for non-tool actions
        """

        intent     = intent_result.get("intent", "chat")
        tool_name  = intent_result.get("tool_name", "")
        tool_args  = intent_result.get("tool_args", {})
        confidence = intent_result.get("confidence", 0.0)

        # logger.info(
        #     f"[router] intent={intent} tool={tool_name} "
        #     f"args={tool_args} conf={confidence:.2f} "
        #     f"pending={pending_tool}"
        # )

        # ── Handle confirm/cancel (response to a previous risky tool ask) ─────
        if intent == "confirm":

            if pending_tool:
                # logger.info(
                #     f"[router] confirmed -> executing "
                #     f"{pending_tool['tool_name']}"
                # )

                return "confirmed", pending_tool, False

            else:
                # logger.warning("[router] confirm with no pending tool")
                return "chat", {}, False

        if intent == "cancel":
            # logger.info("[router] cancelled by user")
            return "cancelled", {}, False

        # ── Handle clarify ────────────────────────────────────────────────────
        if intent == "clarify" or confidence < 0.4:

            # logger.info(
            #     f"[router] needs clarification "
            #     f"(confidence={confidence:.2f})"
            # )

            return "clarify", {}, False

        # ── Handle chat ───────────────────────────────────────────────────────
        if intent == "chat" or not tool_name:
            return "chat", {}, False

        # ── Handle tool_use ───────────────────────────────────────────────────
        if intent == "tool_use":

            if not tool_name:
                # logger.warning(
                #     "[router] tool_use intent but no tool_name"
                # )

                return "clarify", {}, False

            payload = {
                "tool_name": tool_name,
                "tool_args": tool_args
            }

            # Check if this tool needs confirmation
            if tool_name in RISKY_TOOLS:

                # logger.info(
                #     f"[router] risky tool '{tool_name}' "
                #     f"-> requesting confirmation"
                # )

                return "confirm", payload, True

            return "execute", payload, False

        # ── Fallback ──────────────────────────────────────────────────────────
        # logger.warning(f"[router] unhandled intent: {intent}")

        return "chat", {}, False
