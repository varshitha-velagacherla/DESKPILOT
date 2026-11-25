
"""intent_classifier.py

The LLM's ONLY job here is to output structured JSON.
It does NOT call tools. It does NOT generate responses.
It just classifies what the user wants.
"""

import json
import os
import re
import logging
from langchain_ollama import ChatOllama
from langchain_core.messages import SystemMessage, HumanMessage
logger = logging.getLogger("deskpilot.intent")

from dotenv import load_dotenv
load_dotenv()  # take environment variables from .env file

# ── Model config ──────────────────────────────────────────────────────────────
MODEL_NAME = os.getenv("OLLAMA_MODEL")   # change to your model

_llm = ChatOllama(
    model=MODEL_NAME or "qwen2.5:1.5b",
    temperature=0.1,
    base_url="http://localhost:11434",
    format="json",
    num_ctx=1536,
    num_predict=120,
)

# ── The complete tool catalogue given to the classifier ───────────────────────
# The LLM only needs to know tool names and what triggers them.
# It does NOT need implementation details.
TOOL_CATALOGUE = """TOOLS:
open_app(app_name) | close_app(app_name) | list_running_apps()
search_files(filename, extension) | read_file(file_path) | write_file(file_path, content, mode) | delete_file(file_path) | list_directory(folder_path)
get_system_info() | get_battery_status() | set_volume(level: int) | get_clipboard() | set_clipboard(text) | get_current_time()
open_url(url) | web_search(query) | search_and_open(query) | take_screenshot(save_path) | read_screen_text()"""

# ── The classifier prompt ─────────────────────────────────────────────────────
CLASSIFIER_PROMPT = f"""Intent classifier for DeskPilot (Ubuntu voice assistant). Output strict JSON only.

{TOOL_CATALOGUE}

Intents: "tool_use" | "chat" | "clarify" | "confirm" | "cancel"
JSON keys: "intent", "tool_name", "tool_args", "confidence", "raw_query"

Rules:
- If RECENT CONVERSATION is given, resolve "it"/"that"/"this" from it (app -> open_app, website -> open_url).
- Apps (firefox, chrome, vscode, calculator, files) -> open_app; Websites (youtube, gmail, github) -> open_url.
- Chat/questions/jokes/idioms (e.g. "open for it folks", "tell me a joke", "what do I prefer") -> intent="chat", tool_name="", tool_args={{}}.
- "what is the battery" -> get_battery_status; "set volume to X" -> set_volume(level=X); "search for X" -> web_search(query=X).

Examples:
"open firefox" -> {{"intent":"tool_use","tool_name":"open_app","tool_args":{{"app_name":"firefox"}},"confidence":0.99,"raw_query":"open firefox"}}
"open youtube" -> {{"intent":"tool_use","tool_name":"open_url","tool_args":{{"url":"https://youtube.com"}},"confidence":0.99,"raw_query":"open youtube"}}
"set volume to 40 percent" -> {{"intent":"tool_use","tool_name":"set_volume","tool_args":{{"level":40}},"confidence":0.99,"raw_query":"set volume to 40 percent"}}
"search for python tutorials" -> {{"intent":"tool_use","tool_name":"web_search","tool_args":{{"query":"python tutorials"}},"confidence":0.98,"raw_query":"search for python tutorials"}}
"open for it folks" -> {{"intent":"chat","tool_name":"","tool_args":{{}},"confidence":0.9,"raw_query":"open for it folks"}}
"yes go ahead" -> {{"intent":"confirm","tool_name":"","tool_args":{{}},"confidence":0.95,"raw_query":"yes go ahead"}}
"no cancel" -> {{"intent":"cancel","tool_name":"","tool_args":{{}},"confidence":0.95,"raw_query":"no cancel"}}"""

# ── Deterministic pre-LLM regex rules (time / date) ───────────────────────────
_WAKE_PREFIX_RE = re.compile(r"^(?:alexa|hey\s+deskpilot|deskpilot)[,\s]+", re.IGNORECASE)

_TIME_QUERY_PATTERNS = [
    re.compile(r"^(?:what(?:'s| is)\s+(?:the\s+)?(?:current\s+)?time(?:\s+(?:right\s+now|now|today|please))?)$"),
    re.compile(r"^(?:what\s+time\s+is\s+it(?:\s+(?:right\s+now|now|please))?)$"),
    re.compile(r"^(?:(?:please\s+)?tell\s+me\s+(?:the\s+)?(?:current\s+)?time)$"),
    re.compile(r"^(?:(?:what(?:'s| is)\s+)?current\s+time(?:\s+please)?)$"),
    re.compile(r"^(?:do\s+you\s+(?:know|have)\s+the\s+time)$"),
]

_DATE_QUERY_PATTERNS = [
    re.compile(r"^(?:what(?:'s| is)\s+(?:the\s+|today'?s\s+)?date(?:\s+(?:today|please))?)$"),
    re.compile(r"^(?:today'?s\s+date(?:\s+please)?)$"),
    re.compile(r"^(?:what\s+day\s+(?:of\s+the\s+week\s+)?is\s+(?:it|today)(?:\s+(?:today|please))?)$"),
    re.compile(r"^(?:(?:please\s+)?tell\s+me\s+(?:the\s+|today'?s\s+)?date)$"),
    re.compile(r"^(?:current\s+date(?:\s+please)?)$"),
]

_BATTERY_QUERY_PATTERNS = [
    # Broad pattern to catch any phrase mentioning battery
    re.compile(r".*\bbattery\b.*"),

    re.compile(r"^(?:what(?:'s| is)\s+(?:the\s+|my\s+)?battery(?:\s+(?:level|percentage|status))?(?:\s+please)?)$"),
    re.compile(r"^(?:how(?:'s| is)\s+(?:the\s+|my\s+)?battery(?:\s+doing)?(?:\s+please)?)$"),
    re.compile(r"^(?:(?:check|get|show)\s+(?:the\s+|my\s+)?battery(?:\s+(?:level|percentage|status))?)$"),
    re.compile(r"^(?:battery\s+(?:level|percentage|status))$"),
]

_MEMORY_CHAT_PATTERNS = [
    re.compile(r"^(?:remember\s+(?:that|this)\s+.+)$"),
    re.compile(r"^(?:don't\s+forget\s+(?:that\s+)?.+)$"),
    re.compile(r"^(?:what\s+do\s+i\s+(?:prefer|like)|what\s+(?:are|is)\s+my\s+preferences?)$"),
]

_WEB_SEARCH_PATTERN = re.compile(
    r"^(?:(?:please\s+)?(?:search(?:\s+the\s+web)?\s+for|look\s+up|google)\s+)(.+)$"
)

_INVALID_APP_NAMES = {
    "", "for", "it", "that", "this", "the", "a", "an", "to", "in",
    "on", "at", "of", "with", "from", "by", "up", "out", "me", "my",
    "folks", "all", "one", "some", "something", "anything",
}


def _normalize_for_rules(text: str) -> str:
    """Normalize user text for deterministic regex intent matching."""
    cleaned = text.strip().replace("’", "'").replace("‘", "'")
    cleaned = _WAKE_PREFIX_RE.sub("", cleaned)
    cleaned = re.sub(r"[?!.,;:]+$", "", cleaned).strip().lower()
    cleaned = re.sub(r"\s+", " ", cleaned)
    return cleaned


def match_deterministic_intent(user_input: str) -> dict | None:
    """Match unambiguous time/date queries before calling the LLM classifier."""
    norm = _normalize_for_rules(user_input)
    if not norm:
        return None

    for pat in _TIME_QUERY_PATTERNS:
        if pat.match(norm):
            return {
                "intent": "tool_use",
                "tool_name": "get_current_time",
                "tool_args": {"mode": "time"},
                "confidence": 1.0,
                "raw_query": user_input,
            }

    for pat in _DATE_QUERY_PATTERNS:
        if pat.match(norm):
            return {
                "intent": "tool_use",
                "tool_name": "get_current_time",
                "tool_args": {"mode": "date"},
                "confidence": 1.0,
                "raw_query": user_input,
            }

    for pat in _BATTERY_QUERY_PATTERNS:
        if pat.match(norm):
            return {
                "intent": "tool_use",
                "tool_name": "get_battery_status",
                "tool_args": {},
                "confidence": 1.0,
                "raw_query": user_input,
            }

    for pat in _MEMORY_CHAT_PATTERNS:
        if pat.match(norm):
            return {
                "intent": "chat",
                "tool_name": "",
                "tool_args": {},
                "confidence": 1.0,
                "raw_query": user_input,
            }

    m_search = _WEB_SEARCH_PATTERN.match(norm)
    if m_search:
        query = m_search.group(1).strip()
        if query:
            return {
                "intent": "tool_use",
                "tool_name": "web_search",
                "tool_args": {"query": query},
                "confidence": 1.0,
                "raw_query": user_input,
            }

    return None


def classify_intent(user_input: str, memory_context: str = "", conversation_history: list = None) -> dict:
    """
    Classify user input into a structured intent dict.
    Returns a safe default if LLM fails or returns invalid JSON.
    This function NEVER raises — always returns a valid dict.
    """
    deterministic = match_deterministic_intent(user_input)
    if deterministic is not None:
        logger.info(
            f"[classifier] deterministic rule matched: tool={deterministic['tool_name']} "
            f"args={deterministic['tool_args']}"
        )
        return deterministic

    # logger.info(f"[classifier] input: '{user_input}' | history_len={len(conversation_history) if conversation_history else 0}")
    prompt = CLASSIFIER_PROMPT.replace(
        "{tool_catalogue}",
        TOOL_CATALOGUE
    )

    # Build context sections
    context_parts = []
    
    # Add recent conversation history for context (last 3 exchanges)
    if conversation_history:
        # Filter out tool execution messages (they start with "[tool:")
        clean_history = [
            msg for msg in conversation_history 
            if not (msg.type == "ai" and msg.content.startswith("[tool:"))
        ]
        
        recent = clean_history[-6:]  # last 3 user-assistant pairs
        history_lines = []
        for msg in recent:
            role = "User" if msg.type == "human" else "Assistant"
            # Truncate long messages
            content = msg.content[:200] if len(msg.content) > 200 else msg.content
            history_lines.append(f"{role}: {content}")
        
        if history_lines:
            context_parts.append(f"RECENT CONVERSATION:\n" + "\n".join(history_lines))
            # logger.info(f"[classifier] Adding {len(recent)} messages to context")
    
    if memory_context:
        context_parts.append(
            f"MEMORY CONTEXT:\n{memory_context}"
        )
    
    # Keep SystemMessage static so Ollama can reuse its KV prefix cache across turns;
    # dynamic conversation history and memory context go into HumanMessage below.
    if context_parts:
        logger.debug(f"[classifier] Context len={sum(len(p) for p in context_parts)}")
    
    try:
        # Build the user message with context embedded
        user_message = f'Classify this: "{user_input}"'
        
        # If there's conversation history, embed it in the user message
        if context_parts:
            context_str = "\n\n".join(context_parts)
            user_message = f'{context_str}\n\nNow classify this user input: "{user_input}"'
        
        messages = [
            SystemMessage(content=prompt),
            HumanMessage(content=user_message),
        ]

        response = _llm.invoke(messages)
        raw = response.content.strip()
        # logger.debug(f"[classifier] raw LLM output: {raw}")

        # Strip markdown fences if model wrapped JSON in ```json ... ```
        raw = re.sub(r"^```json\s*", "", raw)
        raw = re.sub(r"^```\s*", "", raw)
        raw = re.sub(r"\s*```$", "", raw)

        raw = raw.strip()

        result = json.loads(raw)

        result.setdefault("tool_name", "")
        result.setdefault("tool_args", {})
        if not isinstance(result["tool_args"], dict):
            result["tool_args"] = {}
        result.setdefault("confidence", 0.9)
        result.setdefault("raw_query", user_input)

        if "intent" not in result:
            raise ValueError("Missing field: intent")

        # Validate intent is a known value
        valid_intents = {
            "tool_use",
            "chat",
            "clarify",
            "confirm",
            "cancel"
        }

        if result["intent"] not in valid_intents:
            raise ValueError(f"Unknown intent: {result['intent']}")

        if result["intent"] == "tool_use" and result.get("tool_name") == "open_app":
            app_val = str((result.get("tool_args") or {}).get("app_name", "")).strip().lower()
            if app_val in _INVALID_APP_NAMES:
                logger.info(f"[classifier] rejected invalid open_app target {app_val!r} for {user_input!r}")
                result = {
                    "intent": "clarify",
                    "tool_name": "",
                    "tool_args": {},
                    "confidence": 0.3,
                    "raw_query": user_input,
                }

        return result

    except json.JSONDecodeError as e:
        logger.error(
            f"[classifier] JSON parse failed: {e} | raw='{raw}'"
        )

    except Exception as e:
        logger.error(f"[classifier] failed: {e}")

    # ── Safe fallback — never crash the pipeline ──────────────────────────────
    # logger.warning("[classifier] using fallback: chat intent")

    return {
        "intent": "chat",
        "tool_name": "",
        "tool_args": {},
        "confidence": 0.0,
        "raw_query": user_input,
    }
