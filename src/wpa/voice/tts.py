# ─── TTS Module: pyttsx3 (Offline) ─────────────────────────────

import pyttsx3
import threading
import logging
import time
from queue import Queue

logger = logging.getLogger(__name__)

# Use a queue-based approach to avoid pyttsx3 event loop hanging on Windows
tts_queue = Queue()
tts_thread = None
engine = None
tts_lock = threading.Lock()
is_speaking = False  # Flag to indicate if TTS is currently playing (prevents false wake word detection)

def tts_worker():
    """Background worker thread that handles all TTS operations."""
    global engine, is_speaking
    
    while True:
        try:
            text = tts_queue.get(timeout=1)
            
            if text is None:  # Sentinel value to stop the thread
                break
            
            # Reinitialize engine for each speech (safer on Windows)
            try:
                is_speaking = True  # Signal that TTS is starting
                # logger.debug(f"🔊 TTS starting: '{text[:50]}...' " if len(text) > 50 else f"🔊 TTS starting: '{text}'")
                
                engine = pyttsx3.init()
                engine.setProperty('rate', 180)
                engine.setProperty('volume', 1.0)
                
                # Set Zira voice (female)
                voices = engine.getProperty('voices')
                if voices:
                    for voice in voices:
                        if 'zira' in voice.name.lower():
                            engine.setProperty('voice', voice.id)
                            break
                
                # logger.debug(f"🔊 Speaking: '{text}'")
                engine.say(text)
                engine.runAndWait()
                # logger.debug("✓ Speech finished")
                
            except Exception as e:
                logger.warning(f"TTS error in worker: {e}")
            
            finally:
                # Always clean up the engine and reset flag
                try:
                    if engine:
                        engine.stop()
                except:
                    pass
                engine = None
                is_speaking = False  # Signal that TTS has finished
                # logger.debug("🔇 TTS speaker muted")
        
        except:
            continue

def init_tts_worker():
    """Initialize the TTS background worker thread."""
    global tts_thread
    tts_thread = threading.Thread(target=tts_worker, daemon=True)
    tts_thread.start()
    # logger.info("✅ pyttsx3 worker thread started")

# Start worker on module load
init_tts_worker()

def get_speaking_status() -> bool:
    """
    Check if TTS is currently speaking.
    Used by wake word detector to avoid false detections.
    
    Returns:
        True if currently speaking, False otherwise
    """
    return is_speaking

def speak(text: str, blocking: bool = True, audio_buffer_delay: float = 0.5):
    """
    Speak text aloud using pyttsx3 (offline).
    Queue-based approach to avoid event loop hanging on Windows.
    
    Args:
        text: Text to speak
        blocking: If True, wait for speech to complete
        audio_buffer_delay: Seconds to wait after speaking before resuming listening
                           (prevents picking up own voice)
    """
    if not text or not text.strip():
        logger.debug("Skipped empty text")
        return
    
    try:
        # logger.info(f"🔊 Queuing speech: '{text}'")
        tts_queue.put(text)
        
        if blocking:
            # Estimate time based on text length (roughly 50ms per character)
            estimated_duration = len(text) * 0.05 + 1.0
            
            # Wait for speech to complete
            # logger.debug(f"⏳ Waiting {estimated_duration:.1f}s for TTS to complete...")
            time.sleep(estimated_duration)
            
            # Clear audio buffer: wait a bit longer to let microphone clear
            # This prevents the wake word detector from picking up the tail end of our speech
            if audio_buffer_delay > 0:
                # logger.debug(f"🔇 Audio buffer clear delay: {audio_buffer_delay}s")
                time.sleep(audio_buffer_delay)
    
    except Exception as e:
        logger.error(f"Error queuing TTS: {e}", exc_info=True)

def test_voice():
    """Test the TTS voice with a sample message."""
    test_messages = [
        "Hello! I am your Windows Productivity Agent.",
        "I can open applications, search the web, and control your system."
    ]
    
    for msg in test_messages:
        print(f"Speaking: {msg}")
        speak(msg, blocking=True)
        time.sleep(0.5)

# logger.info("✅ Offline TTS module (pyttsx3) ready!")

if __name__ == "__main__":
    test_voice()

