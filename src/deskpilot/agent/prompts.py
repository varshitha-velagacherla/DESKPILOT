
from langchain_core import prompts



"""All prompt strings in one place.
In the hybrid architecture, prompts are only used by:
  1. intent_classifier.py  → CLASSIFIER_PROMPT (in that file, self-contained)
  2. response_generator.py → all RESPONSE_* prompts (in that file, self-contained)
  
This file is kept for any shared constants and future additions."""


# Risky tools that require confirmation
RISKY_TOOLS = {
    "delete_file",
    "write_file",
    "close_app",
    "set_volume",
    "set_clipboard",
}

# User confirmation phrases
CONFIRM_PHRASES = {
    "yes", "yeah", "yep", "yup", "sure", "ok", "okay",
    "go ahead", "proceed", "do it", "confirm", "correct",
    "right", "affirmative", "please do", "yes please",
}

# User cancellation phrases
CANCEL_PHRASES = {
    "no", "nope", "nah", "cancel", "stop", "abort",
    "don't", "do not", "never mind", "forget it",
    "skip it", "negative",
}

# Session stop phrases
STOP_PHRASES = {
    "goodbye", "good bye", "bye", "exit", "quit",
    "shut down", "turn off", "stop agent",
}