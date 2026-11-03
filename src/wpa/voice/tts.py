"""
tts.py — pyttsx3 TTS, Linux port

Changes from Windows version:
  - Removed Zira (Windows SAPI5) voice selection
  - Selects first available espeak-ng voice; falls back to index 0 if none
  - Comment about "safer on Windows" removed
  - Queue-based worker approach retained (works well on Linux too)
"""

import pyttsx3
import threading
import logging
import time
from queue import Queue

logger = logging.getLogger(__name__)

tts_queue  = Queue()
tts_thread = None
engine     = None
tts_lock   = threading.Lock()
is_speaking = False  # Flag used by VAD/wakeword to skip frames during speech


def tts_worker():
    """Background worker thread that handles all TTS operations."""
    global engine, is_speaking

    while True:
        try:
            text = tts_queue.get(timeout=1)

            if text is None:   # Sentinel to stop the thread
                break

            try:
                is_speaking = True

                engine = pyttsx3.init()
                engine.setProperty("rate", 160)    # slightly slower; espeak default is fast
                engine.setProperty("volume", 1.0)

                # Linux voice selection: prefer espeak-ng, fall back to first available
                voices = engine.getProperty("voices")
                if voices:
                    # Try to find an English espeak voice
                    selected = None
                    for v in voices:
                        vid = (v.id or "").lower()
                        if "english" in vid or "en" in vid or "espeak" in vid:
                            selected = v.id
                            break
                    if selected:
                        engine.setProperty("voice", selected)
                    # else: use default (index 0 is fine on espeak-ng)

                engine.say(text)
                engine.runAndWait()

            except Exception as e:
                logger.warning(f"TTS error in worker: {e}")

            finally:
                try:
                    if engine:
                        engine.stop()
                except Exception:
                    pass
                engine      = None
                is_speaking = False

        except Exception:
            continue


def init_tts_worker():
    """Initialize the TTS background worker thread."""
    global tts_thread
    tts_thread = threading.Thread(target=tts_worker, daemon=True)
    tts_thread.start()


# Start worker on module load
init_tts_worker()


def get_speaking_status() -> bool:
    """Check if TTS is currently speaking (used by wakeword/VAD to skip frames)."""
    return is_speaking


def speak(text: str, blocking: bool = True, audio_buffer_delay: float = 0.5):
    """
    Speak text aloud using pyttsx3 (offline, espeak-ng backend on Linux).
    Queue-based to avoid event-loop conflicts on Linux.

    Args:
        text:              Text to speak
        blocking:          If True, wait for estimated speech duration
        audio_buffer_delay: Extra seconds after speech to let mic clear
    """
    if not text or not text.strip():
        return

    try:
        tts_queue.put(text)

        if blocking:
            # Estimate duration: ~50ms per character; at least 1s
            estimated_duration = len(text) * 0.05 + 1.0
            time.sleep(estimated_duration)

            if audio_buffer_delay > 0:
                time.sleep(audio_buffer_delay)

    except Exception as e:
        logger.error(f"Error queuing TTS: {e}", exc_info=True)


if __name__ == "__main__":
    speak("Hello! I am the Linux Productivity Agent, running on Ubuntu.")
