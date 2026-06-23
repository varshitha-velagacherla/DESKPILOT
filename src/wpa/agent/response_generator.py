
"""response_generator.py

The LLM's second and final job:
Take a tool result (or chat input) and format it into
natural spoken language for TTS.

The LLM never decides WHAT to do here — only HOW to say the result.
"""

import logging
import os
from typing import List
from dotenv import load_dotenv
load_dotenv()  # take environment variables from .env file

from langchain_ollama import ChatOllama
from langchain_core.messages import (
    SystemMessage,
    HumanMessage,
    BaseMessage,
)

logger = logging.getLogger("wpa.responder")

MODEL_NAME = os.getenv("OLLAMA_MODEL")   # same model as classifier, change if needed

_llm = ChatOllama(
    model=MODEL_NAME,
    temperature=0.4,
    base_url="http://localhost:11434",
)

# ── Prompts for each response type ───────────────────────────────────────────

TOOL_SUCCESS_PROMPT = """
You are a voice assistant. A tool just ran successfully.
Convert the tool result into ONE natural spoken sentence.

Rules:
- Maximum 1-2 sentences
- No markdown, no bullet points, no asterisks
- State the result directly and clearly
- Do not say "It seems like" or "That's correct"
- Do not ask follow-up questions
- Do not mention tool names or technical terms

Examples:

Tool: get_current_time
Result: "It is Friday, May 08 2026, 03:41 PM"
Response: "It is 3:41 PM on Friday, May 8th."

Tool: get_battery_status
Result: "Battery is at 45%, discharging."
Response: "Your battery is at 45 percent and discharging."

Tool: open_app
Result: "Opened notepad successfully."
Response: "Notepad is open."

Tool: get_system_info
Result: "CPU: 14%, RAM: 73% used, Battery: 45%"
Response: "CPU is at 14 percent, RAM at 73 percent, and battery at 45 percent."
"""

TOOL_FAILURE_PROMPT = """
You are a voice assistant. A tool just failed.

Explain the failure in ONE natural spoken sentence.

Rules:
- Be honest but friendly
- No technical jargon
- No error codes
- Suggest what the user could do instead if obvious
- Maximum 1 sentence
"""

CHAT_PROMPT = """
You are WPA, the Windows Productivity Agent,
a friendly offline voice assistant.

Answer the user's question or respond to their message.

Rules:
- Maximum 2 sentences
- No markdown
- No bullet points
- Conversational and natural
- This will be spoken aloud
- If asked what you can do, say:
  I can open apps, manage files,
  check system info, control volume,
  take screenshots, and search the web.
- Do not call any tools
- Do not output JSON
- Never claim an action was performed
- Never say an app was opened unless tool execution actually happened
- Never invent tool outputs
- If no tool was executed, only respond conversationally
"""

CLARIFY_PROMPT = """
You are a voice assistant.

The user's request was unclear.

Ask ONE short clarifying question to understand what they want.

Maximum 1 sentence.
No markdown.
"""

CONFIRM_PROMPT = """
You are a voice assistant about to perform
an action that cannot be undone.

In ONE sentence:
- tell the user exactly what you are about to do
- ask if they want to proceed

Be specific.
No markdown.

Example:
"I am about to set the volume to 40 percent.
Should I go ahead?"

Example:
"I am about to delete the file tasks.txt.
Should I proceed?"
"""

CANCEL_PROMPT = """
You are a voice assistant.

The user just cancelled an action.

Acknowledge the cancellation in ONE short sentence.

No markdown.

Example:
"Okay, I have cancelled that."
"""


def generate_response(
    response_type: str,
    tool_name: str = "",
    tool_args: dict = None,
    tool_output: str = "",
    user_input: str = "",
    history: List[BaseMessage] = None,
) -> str:
    """
    Generate a natural spoken response.

    response_type:
        "tool_success"
        "tool_failure"
        "chat"
        "clarify"
        "confirm"
        "cancel"
    """

    tool_args = tool_args or {}
    history = history or []

    # logger.info(
    #     f"[responder] type={response_type} tool={tool_name}"
    # )

    try:

        if response_type == "tool_success":

            messages = [
                SystemMessage(content=TOOL_SUCCESS_PROMPT),

                HumanMessage(
                    content=(
                        f"Tool: {tool_name}\n"
                        f"Args: {tool_args}\n"
                        f"Result: {tool_output}\n"
                        f"Convert this to a natural spoken sentence."
                    )
                ),
            ]

        elif response_type == "tool_failure":

            messages = [
                SystemMessage(content=TOOL_FAILURE_PROMPT),

                HumanMessage(
                    content=(
                        f"Tool: {tool_name}\n"
                        f"Error: {tool_output}\n"
                        f"Explain this failure naturally."
                    )
                ),
            ]

        elif response_type == "chat":

            messages = [
                SystemMessage(content=CHAT_PROMPT),

                *history[-6:],   # last 3 turns for context

                HumanMessage(content=user_input),
            ]

        elif response_type == "clarify":

            messages = [
                SystemMessage(content=CLARIFY_PROMPT),

                HumanMessage(
                    content=(
                        f"User said: '{user_input}'\n"
                        f"Ask a clarifying question."
                    )
                ),
            ]

        elif response_type == "confirm":

            messages = [
                SystemMessage(content=CONFIRM_PROMPT),

                HumanMessage(
                    content=(
                        f"Tool: {tool_name}\n"
                        f"Args: {tool_args}\n"
                        f"Ask for confirmation."
                    )
                ),
            ]

        elif response_type == "cancel":

            messages = [
                SystemMessage(content=CANCEL_PROMPT),

                HumanMessage(
                    content="User cancelled the action."
                ),
            ]

        else:
            logger.warning(
                f"[responder] unknown type: {response_type}"
            )

            return "Done."

        response = _llm.invoke(messages)

        text = response.content.strip()

        # Strip any markdown that leaked through
        for ch in ["**", "*", "##", "#", "`", "_"]:
            text = text.replace(ch, "")

        text = text.strip()

        # logger.info(
        #     f"[responder] output: {text[:100]}"
        # )

        return text or "Done."

    except Exception as e:

        logger.error(
            f"[responder] failed: {e}"
        )

        return "I encountered an error generating a response."

