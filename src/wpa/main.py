"""
main.py  —  Windows Productivity Agent

Fixes from previous version:
  1. signal_handler only sets flag — never calls sys.exit() or speak()
  2. Tray exit uses a simple flag callback, not sys.exit()
  3. is_paused() checked in BOTH the main loop AND inside conversation session
  4. set_status() called at each stage so tray tooltip is always current
"""

import logging
import sys
import signal
import time
import os
import uuid
import requests
from dotenv import load_dotenv

from src.wpa.voice.wakeword import WakeWordDetector
from src.wpa.voice.stt      import record_until_silence, transcribe_audio
from src.wpa.voice.tts      import speak
from src.wpa.agent          import agent, AgentState
from src.wpa.ui.tray        import start_tray, set_status, is_paused, exit_requested

load_dotenv()

# ─── Logging ──────────────────────────────────────────────────────────────────
os.makedirs("logs",   exist_ok=True)
os.makedirs("memory", exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[
        logging.FileHandler("logs/wpa.log"),
        # logging.StreamHandler(sys.stdout),  # Disabled terminal output
    ]
)
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)
logger = logging.getLogger(__name__)

# ─── Config ───────────────────────────────────────────────────────────────────
OLLAMA_API_URL           = os.getenv("OLLAMA_API_URL",           "http://localhost:11434")
OLLAMA_MODEL             = os.getenv("OLLAMA_MODEL",             "llama3.1:8b")
WAKE_WORD                = os.getenv("WAKE_WORD",                "hey_jarvis")
WAKE_WORD_THRESHOLD      = float(os.getenv("WAKE_WORD_THRESHOLD",     "0.05"))
WAKE_WORD_TIMEOUT        = int(os.getenv("WAKE_WORD_TIMEOUT",         "30"))
CONVERSATION_TIMEOUT     = int(os.getenv("CONVERSATION_TIMEOUT",      "15"))
AUDIO_BUFFER_CLEAR_DELAY = float(os.getenv("AUDIO_BUFFER_CLEAR_DELAY","0.5"))
MEMORY_MAX_MESSAGES      = int(os.getenv("MEMORY_MAX_MESSAGES",        "20"))

STOP_PHRASES = {"goodbye", "bye", "exit", "quit", "stop", "thank you"}

# ─── Global state ─────────────────────────────────────────────────────────────
wake_word_detector  = None
is_running          = True
conversation_memory = []
pending_tool        = {}
SESSION_ID          = str(uuid.uuid4())[:8]


# ══════════════════════════════════════════════════════════════════════════════
# SIGNAL HANDLER
# ══════════════════════════════════════════════════════════════════════════════

def signal_handler(sig, frame):
    """
    FIX: Only sets is_running=False.
    Never calls sys.exit() — that raises SystemExit which
    pystray catches as an unhandled error in its message loop.
    Never calls speak() — TTS thread may be shutting down.
    """
    global is_running
    print("\nShutting down...")
    is_running = False


# ══════════════════════════════════════════════════════════════════════════════
# AGENT RUNNER
# ══════════════════════════════════════════════════════════════════════════════

def run_agent(user_input: str, debug: bool = False) -> str:
    global conversation_memory, pending_tool

    # Trim to prevent unbounded memory growth
    if len(conversation_memory) > MEMORY_MAX_MESSAGES:
        conversation_memory = conversation_memory[-MEMORY_MAX_MESSAGES:]

    state = AgentState(
        user_input         = user_input,
        agent_response     = "",
        messages           = conversation_memory,
        intent_result      = {},
        memory_context     = "",
        tool_name          = "",
        tool_args          = {},
        tool_output        = "",
        tool_success       = False,
        needs_confirmation = False,
        confirmed          = False,
        pending_tool       = pending_tool,
        session_id         = SESSION_ID,
        turn_number        = len(conversation_memory) // 2,
        error_message      = "",
        _routing_action    = "",
    )

    result = agent.invoke(state)

    conversation_memory = result.get("messages", [])
    action              = result.get("_routing_action", "")
    pending_tool        = result.get("pending_tool", {}) if action == "confirm" else {}

    response     = result.get("agent_response", "")
    tool_used    = result.get("tool_name",      "")
    tool_success = result.get("tool_success",   False)
    intent       = result.get("intent_result",  {})

    print(f"\n{'─'*55}")
    print(f"You : {user_input}")

    if debug:
        print(f"     intent = {intent.get('intent')} "
              f"(conf={intent.get('confidence', 0):.2f})")
        print(f"     tool   = {intent.get('tool_name')}")
        print(f"     action = {action}")

    if tool_used:
        if   action == "confirm":                status = "PENDING"
        elif action in ("execute", "confirmed"): status = "OK" if tool_success else "FAIL"
        else:                                    status = "SKIPPED"
        print(f"     [{status}] {tool_used}")
        if debug:
            print(f"     output : {result.get('tool_output', '')[:120]}")

    if action == "confirm":
        print(f"WPA : {response}")
        print(f"     >>> Say 'yes' to confirm or 'no' to cancel")
    else:
        print(f"WPA : {response}")

    return response


# ══════════════════════════════════════════════════════════════════════════════
# INIT
# ══════════════════════════════════════════════════════════════════════════════

def initialize_pipeline() -> bool:
    global wake_word_detector

    logger.info("Initializing Windows Productivity Agent...")

    # Check Ollama
    try:
        resp   = requests.get(f"{OLLAMA_API_URL}/api/tags", timeout=5)
        models = [m["name"] for m in resp.json().get("models", [])]
        logger.info(f"Ollama available. Models: {models}")
        if OLLAMA_MODEL not in str(models):
            logger.warning(f"Model '{OLLAMA_MODEL}' not found. Run: ollama pull {OLLAMA_MODEL}")
    except Exception as e:
        logger.error(f"Ollama not reachable: {e}. Run: ollama serve")
        return False

    # Wake word
    try:
        wake_word_detector = WakeWordDetector(
            wake_word = WAKE_WORD,
            threshold = WAKE_WORD_THRESHOLD
        )
        # logger.info(f"Wake word ready ('{WAKE_WORD}' threshold={WAKE_WORD_THRESHOLD})")
    except Exception as e:
        logger.error(f"Wake word init failed: {e}")
        return False

    # Tray — FIX: callback only sets flag, no sys.exit()
    def _tray_exit():
        global is_running
        logger.info("Tray exit clicked → stopping main loop")
        is_running = False

    start_tray(on_exit_callback=_tray_exit)
    logger.info("System tray started")

    # TTS
    try:
        speak("I am online.")
    except Exception as e:
        logger.warning(f"TTS startup failed: {e}")

    return True


# ══════════════════════════════════════════════════════════════════════════════
# WAKE WORD
# ══════════════════════════════════════════════════════════════════════════════

def listen_for_wake_word() -> bool:
    # logger.info(f"Waiting for wake word ({WAKE_WORD_TIMEOUT}s)...")
    detected = wake_word_detector.listen(timeout=WAKE_WORD_TIMEOUT)
    if not detected:
        return False
    # logger.info("Wake word detected!")
    speak("Yes? How can I help you?")
    return True


# ══════════════════════════════════════════════════════════════════════════════
# CONVERSATION SESSION
# ══════════════════════════════════════════════════════════════════════════════

def run_conversation_session() -> bool:
    """
    Returns True  → go back to wake word listening
    Returns False → full shutdown
    """
    last_activity = time.time()
    # logger.info(f"Conversation started (idle timeout={CONVERSATION_TIMEOUT}s)")

    while True:

        # Global shutdown check
        if not is_running or exit_requested():
            return False

        # FIX: pause check inside conversation loop
        # Before: pausing mid-conversation had no effect — recording continued.
        # Now: if user pauses via tray during a session, we wait here.
        if is_paused():
            logger.debug("Paused mid-conversation — waiting...")
            time.sleep(0.2)
            last_activity = time.time()   # reset idle timer while paused
            continue

        # Idle timeout
        if time.time() - last_activity >= CONVERSATION_TIMEOUT:
            # logger.info("Conversation idle timeout")
            speak("Conversation ended.")
            return True

        try:
            # Record
            set_status("Listening to you...")
            # logger.info("Recording speech...")
            audio = record_until_silence(
                speech_start_timeout_s = 5,
                silence_threshold_ms   = 2000,
                max_duration_s         = 10,
            )

            if audio is None or len(audio) == 0:
                logger.warning("No audio this turn")
                speak("I am listening.")
                continue

            # Transcribe
            set_status("Transcribing...")
            text = transcribe_audio(audio)

            if not text or not text.strip():
                speak("I am listening.")
                continue

            # logger.info(f"Transcript: '{text}'")
            last_activity = time.time()

            # Stop phrase
            if any(p in text.lower() for p in STOP_PHRASES):
                logger.info(f"Stop phrase: '{text}'")
                speak("Goodbye! Have a great day.")
                return False

            # Agent
            set_status("Thinking...")
            response = run_agent(text)

            set_status("Speaking...")
            speak(response)
            time.sleep(AUDIO_BUFFER_CLEAR_DELAY)

            last_activity = time.time()

        except KeyboardInterrupt:
            raise
        except Exception as e:
            logger.error(f"Conversation error: {e}", exc_info=True)
            try:
                speak("Something went wrong. Please try again.")
            except Exception:
                pass
            continue

    return True


# ══════════════════════════════════════════════════════════════════════════════
# MAIN LOOP
# ══════════════════════════════════════════════════════════════════════════════

def main():
    print("\n" + "=" * 60)
    print("      Windows Productivity Agent (WPA)")
    print("=" * 60)

    signal.signal(signal.SIGINT, signal_handler)

    if not initialize_pipeline():
        logger.error("Initialization failed — exiting")
        return

    print(f"\nSay '{WAKE_WORD}' to activate")
    print(f"Right-click tray icon to Pause or Exit\n")

    session_count = 0

    while is_running and not exit_requested():
        try:
            time.sleep(0.05)

            # Pause check — stops wake word listening when paused
            if is_paused():
                set_status("Paused")
                continue

            set_status("Listening for wake word...")

            if not listen_for_wake_word():
                continue

            session_count += 1
            # logger.info(f"Session {session_count} started")
            set_status("In conversation...")

            should_continue = run_conversation_session()

            logger.info(
                f"Session {session_count} ended | "
                f"memory={len(conversation_memory)} messages"
            )

            if not should_continue:
                break

        except KeyboardInterrupt:
            break
        except Exception as e:
            logger.error(f"Main loop error: {e}", exc_info=True)
            time.sleep(1)
            continue

    logger.info(f"WPA shut down after {session_count} sessions")
    print("Goodbye!")


if __name__ == "__main__":
    main()