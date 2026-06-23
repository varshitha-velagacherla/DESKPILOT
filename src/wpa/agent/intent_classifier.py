
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
logger = logging.getLogger("wpa.intent")

from dotenv import load_dotenv
load_dotenv()  # take environment variables from .env file

# ── Model config ──────────────────────────────────────────────────────────────
MODEL_NAME = os.getenv("OLLAMA_MODEL")   # change to your model

_llm = ChatOllama(
    model=MODEL_NAME,
    temperature=0.1,          
    base_url="http://localhost:11434",
    format="json",            # force JSON output mode
)

# ── The complete tool catalogue given to the classifier ───────────────────────
# The LLM only needs to know tool names and what triggers them.
# It does NOT need implementation details.
TOOL_CATALOGUE = """
AVAILABLE TOOLS:
- open_app(app_name: str)          → open an application
- close_app(app_name: str)         → close a running application  
- list_running_apps()              → list what apps are open
- search_files(filename, extension)→ find files on the PC
- read_file(file_path)             → read contents of a file
- write_file(file_path, content, mode) → create or append to a file
- delete_file(file_path)           → delete a file permanently
- list_directory(folder_path)      → list files in a folder
- get_system_info()                → CPU, RAM, battery, disk, time
- get_battery_status()             → battery percentage and charging state
- set_volume(level: int)           → set system volume 0-100
- get_clipboard()                  → read clipboard contents
- set_clipboard(text)              → copy text to clipboard
- get_current_time()               → current date and time
- open_url(url)                    → open URL in browser
- web_search(query)                → search the web
- search_and_open(query)           → search web and open top result
- take_screenshot(save_path)       → capture the screen
- read_screen_text()               → OCR all visible text on screen
"""

# ── The classifier prompt ─────────────────────────────────────────────────────
CLASSIFIER_PROMPT = f"""
You are an intent classifier for a Windows voice assistant.
Your ONLY job is to output valid JSON. Nothing else.

{TOOL_CATALOGUE}

INTENTS:
- "tool_use"  → user wants to do something on the PC (use a tool)
- "chat"      → general question or conversation (no tool needed)
- "clarify"   → request is too vague to determine which tool
- "confirm"   → user is saying yes/confirming a previous action
- "cancel"    → user is saying no/cancelling a previous action

CRITICAL: When RECENT CONVERSATION is provided:
- ALWAYS check it first before classifying
- Look for app/website/file names mentioned by the user in recent messages
- Resolve "that", "it", "this" by finding the subject from the conversation
- Example: If user asked "Why YouTube?" and now says "open that" → extract app_name="youtube"
- DO NOT use "clarify" intent if the conversation context makes it obvious

OUTPUT FORMAT (strict JSON, nothing else):
{{
  "intent": "tool_use" | "chat" | "clarify" | "confirm" | "cancel",
  "tool_name": "exact_tool_name_or_empty_string",
  "tool_args": {{}},
  "confidence": 0.0-1.0,
  "raw_query": "the original user input"
}}

RULES:
- If intent is "chat", set tool_name to "" and tool_args to {{}}
- If intent is "tool_use", always set tool_name to one of the exact tool names above
- For set_volume, extract the number from the query for the level arg
- For open_app/close_app, extract the app name for app_name arg
- For write_file, extract file path and content
- Confidence should reflect how certain you are (0.9+ for clear requests)

EXAMPLES:
User: "open notepad"
{{"intent":"tool_use","tool_name":"open_app","tool_args":{{"app_name":"notepad"}},"confidence":0.99,"raw_query":"open notepad"}}

User: "open youtube"
{{"intent":"tool_use","tool_name":"open_url","tool_args":{{"url":"https://youtube.com"}},"confidence":0.99,"raw_query":"open youtube"}}

User: "open gmail"
{{"intent":"tool_use","tool_name":"open_url","tool_args":{{"url":"https://gmail.com"}},"confidence":0.99,"raw_query":"open gmail"}}

User: "what time is it"
{{"intent":"tool_use","tool_name":"get_current_time","tool_args":{{}},"confidence":0.98,"raw_query":"what time is it"}}

User: "hello how are you"
{{"intent":"chat","tool_name":"","tool_args":{{}},"confidence":0.97,"raw_query":"hello how are you"}}

User: "set volume to 40"
{{"intent":"tool_use","tool_name":"set_volume","tool_args":{{"level":40}},"confidence":0.99,"raw_query":"set volume to 40"}}

User: "yes go ahead"
{{"intent":"confirm","tool_name":"","tool_args":{{}},"confidence":0.95,"raw_query":"yes go ahead"}}

User: "no cancel that"
{{"intent":"cancel","tool_name":"","tool_args":{{}},"confidence":0.95,"raw_query":"no cancel that"}}

User: "do the thing"
{{"intent":"clarify","tool_name":"","tool_args":{{}},"confidence":0.3,"raw_query":"do the thing"}}

CONTEXT RESOLUTION EXAMPLES:
RECENT CONVERSATION:
User: Why do we use Spotify?
Assistant: Spotify is a music streaming service...
User: "open that"
{{"intent":"tool_use","tool_name":"open_app","tool_args":{{"app_name":"spotify"}},"confidence":0.95,"raw_query":"open that"}}

RECENT CONVERSATION:
User: Tell me about Chrome
Assistant: Chrome is a web browser...
User: "launch it"
{{"intent":"tool_use","tool_name":"open_app","tool_args":{{"app_name":"chrome"}},"confidence":0.95,"raw_query":"launch it"}}

RECENT CONVERSATION:
User: Why do we use YouTube?
Assistant: YouTube is a video platform...
User: "that"
{{"intent":"tool_use","tool_name":"open_url","tool_args":{{"url":"https://youtube.com"}},"confidence":0.95,"raw_query":"that"}}

NOTE: For apps like Spotify, Chrome, VS Code, use open_app. For websites like YouTube, GitHub, use open_url.

When extracting app names:
- Correct obvious spelling mistakes
- Normalize common aliases
- Use the closest valid application name when confidence is high
- For WEBSITES (YouTube, Gmail, GitHub, Reddit, Twitter, Facebook, etc.) use open_url, NOT open_app
- For APPLICATIONS (Chrome, VS Code, Notepad, Calculator, Spotify app, etc.) use open_app

Examples:
"open chromee" -> open_app(app_name="chrome")
"launch vlcc" -> open_app(app_name="vlc")
"open calcultor" -> open_app(app_name="calculator")
"open youtube" -> open_url(url="https://youtube.com")
"open gmail" -> open_url(url="https://gmail.com")
"open github" -> open_url(url="https://github.com")
"""

def classify_intent(user_input: str, memory_context: str = "", conversation_history: list = None) -> dict:
    """
    Classify user input into a structured intent dict.
    Returns a safe default if LLM fails or returns invalid JSON.
    This function NEVER raises — always returns a valid dict.
    """
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
    
    # Prepend context to prompt
    if context_parts:
        full_context = "\n\n".join(context_parts) + "\n\n"
        logger.debug(f"[classifier] Context:\n{full_context[:300]}...")
        prompt = full_context + prompt
    
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

        # Validate required fields exist
        required = [
            "intent",
            "tool_name",
            "tool_args",
            "confidence",
            "raw_query"
        ]

        for field in required:
            if field not in result:
                raise ValueError(f"Missing field: {field}")

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

        # logger.info(
        #     f"[classifier] intent={result['intent']} "
        #     f"tool={result['tool_name']} "
        #     f"args={result['tool_args']} "
        #     f"confidence={result['confidence']:.2f}"
        # )

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
