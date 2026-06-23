"""
stt.py  —  Speech-to-Text + VAD Pipeline

Changes from previous version:
  1. speech_start_timeout added — stops waiting if user never speaks
  2. pre_speech_buffer capped at max 1s to prevent unbounded growth
  3. TTS check moved outside loop (import once, call each frame)
  4. Silence/duration values updated to recommended best-practice defaults
  5. Better per-stage logging so you can see exactly where time is spent
"""

import numpy as np
import sounddevice as sd
import soundfile as sf
import tempfile
import os
import logging
import time
import torch
import pyaudio
from faster_whisper import WhisperModel
from silero_vad import load_silero_vad

logger = logging.getLogger(__name__)

# ── Whisper STT model ─────────────────────────────────────────────────────────
try:
    STT_MODEL = WhisperModel("small", device="cpu", compute_type="int8")
    logger.info("Whisper STT model loaded (small/cpu/int8)")
except Exception as e:
    logger.error(f"Failed to load Whisper model: {e}", exc_info=True)
    STT_MODEL = None

SAMPLE_RATE = 16000  # Whisper expects 16kHz

# ── Silero VAD model ──────────────────────────────────────────────────────────
try:
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    vad_model = load_silero_vad().to(device)
    # logger.info(f"Silero VAD model loaded (device: {device})")
except Exception as e:
    logger.error(f"Failed to load VAD model: {e}", exc_info=True)
    vad_model = None


# ══════════════════════════════════════════════════════════════════════════════
# FIXED-DURATION RECORDING  (used for testing only)
# ══════════════════════════════════════════════════════════════════════════════

def record_audio(duration: int = 5, sample_rate: int = SAMPLE_RATE) -> np.ndarray:
    """
    Record audio for a fixed duration.
    Use record_until_silence() in production — this is for testing only.
    """
    try:
        # logger.info(f"Recording {duration}s (fixed duration)...")
        audio = sd.rec(
            int(duration * sample_rate),
            samplerate=sample_rate,
            channels=1,
            dtype="float32"
        )
        sd.wait()
        return audio.flatten()
    except Exception as e:
        logger.error(f"record_audio failed: {e}", exc_info=True)
        return np.array([])


# ══════════════════════════════════════════════════════════════════════════════
# TRANSCRIPTION
# ══════════════════════════════════════════════════════════════════════════════

def transcribe_audio(audio: np.ndarray, sample_rate: int = SAMPLE_RATE) -> str:
    """
    Transcribe a numpy audio array using faster-whisper.

    Args:
        audio:       float32 numpy array at 16kHz
        sample_rate: must match the audio (default 16000)

    Returns:
        Transcribed text, or "" on failure.
    """
    if STT_MODEL is None:
        logger.error("Whisper model not loaded — cannot transcribe")
        return ""

    if audio is None or len(audio) == 0:
        logger.warning("transcribe_audio called with empty audio")
        return ""

    tmp_path = None
    try:
        t0 = time.time()

        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
            sf.write(tmp.name, audio, sample_rate)
            tmp_path = tmp.name

        duration_s = len(audio) / sample_rate
        # logger.info(f"Transcribing {duration_s:.2f}s of audio...")

        segments, info = STT_MODEL.transcribe(
            tmp_path,
            language="en",
            vad_filter=True,
            vad_parameters=dict(min_silence_duration_ms=500)
        )
        text = " ".join(seg.text for seg in segments).strip()

        elapsed = time.time() - t0
        # logger.info(f"Transcription done in {elapsed:.2f}s: '{text}'")
        return text

    except Exception as e:
        logger.error(f"Transcription failed: {e}", exc_info=True)
        return ""

    finally:
        if tmp_path and os.path.exists(tmp_path):
            try:
                os.unlink(tmp_path)
            except Exception:
                pass


# ══════════════════════════════════════════════════════════════════════════════
# VAD-BASED RECORDING  (production)
# ══════════════════════════════════════════════════════════════════════════════

def record_until_silence(
    sample_rate:           int   = SAMPLE_RATE,
    speech_start_timeout_s: int  = 5,      # CHANGED: was missing — stop if user never speaks
    silence_threshold_ms:  int   = 2000,   # CHANGED: was 1500 → 2000ms (recommended)
    max_duration_s:        int   = 10,     # unchanged
    speech_threshold:      float = 0.5,    # unchanged
    pre_buffer_max_s:      float = 0.5,    # CHANGED: cap pre-speech buffer at 0.5s
) -> np.ndarray:
    """
    Record audio from mic until silence is detected using Silero VAD.

    Stages:
      1. Waiting for speech  → stops after speech_start_timeout_s if nobody speaks
      2. Recording speech    → stops after silence_threshold_ms of silence
      3. Hard cap            → stops after max_duration_s regardless

    Args:
        sample_rate:            16000 Hz (Whisper requirement)
        speech_start_timeout_s: give up waiting for speech after N seconds (NEW)
        silence_threshold_ms:   stop recording after N ms of silence
        max_duration_s:         hard maximum recording length
        speech_threshold:       Silero VAD confidence threshold (0–1)
        pre_buffer_max_s:       how many seconds of audio to keep before speech starts

    Returns:
        float32 numpy array, or empty array if nothing recorded.
    """
    if vad_model is None:
        logger.error("VAD model not loaded — cannot record")
        return np.array([])

    # ── Frame sizing ──────────────────────────────────────────────────────────
    # Silero VAD minimum is 512 samples at 16kHz = 32ms
    frame_duration_ms = 32
    frame_size        = int(sample_rate * frame_duration_ms / 1000)  # 512 samples

    silence_limit         = int(silence_threshold_ms   / frame_duration_ms)
    speech_start_limit    = int(speech_start_timeout_s * 1000 / frame_duration_ms)
    max_frames            = int(max_duration_s         * 1000 / frame_duration_ms)
    pre_buffer_max_frames = int(pre_buffer_max_s       * 1000 / frame_duration_ms)

    # ── Resolve TTS status function ONCE (not inside the hot loop) ────────────
    # CHANGE: was doing `from src.wpa.voice.tts import get_speaking_status`
    # inside every frame iteration — that's a Python import lookup on every frame.
    # We resolve it once here and pass the function reference into the loop.
    try:
        from src.wpa.voice.tts import get_speaking_status as _tts_status
    except ImportError:
        _tts_status = None
        logger.debug("TTS status check unavailable — will not skip TTS frames")

    pa     = pyaudio.PyAudio()
    stream = None

    try:
        stream = pa.open(
            format=pyaudio.paInt16,
            channels=1,
            rate=sample_rate,
            input=True,
            frames_per_buffer=frame_size
        )

        # logger.info("Listening... (Silero VAD)")

        frames          = []
        pre_buffer      = []       # audio before speech starts (capped)
        silence_frames  = 0
        speech_started  = False
        waiting_frames  = 0        # frames spent waiting for speech to begin

        for _ in range(max_frames):

            # ── Skip frames while TTS is speaking ─────────────────────────────
            # CHANGE: TTS check is now a simple function call (resolved above)
            if _tts_status is not None:
                try:
                    if _tts_status():
                        stream.read(frame_size, exception_on_overflow=False)
                        continue
                except Exception:
                    pass

            # ── Read one frame from mic ────────────────────────────────────────
            try:
                raw = stream.read(frame_size, exception_on_overflow=False)
            except Exception as e:
                logger.warning(f"Stream read error: {e}")
                continue

            # ── Run VAD ───────────────────────────────────────────────────────
            audio_f32    = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
            audio_tensor = torch.from_numpy(audio_f32).unsqueeze(0).to(device)

            with torch.no_grad():
                speech_prob = vad_model(audio_tensor, sample_rate).item()

            is_speech = speech_prob > speech_threshold

            # ── State machine ─────────────────────────────────────────────────
            if not speech_started:
                # Waiting for speech to begin

                # CHANGE: cap pre-buffer so it doesn't grow unbounded
                pre_buffer.append(raw)
                if len(pre_buffer) > pre_buffer_max_frames:
                    pre_buffer.pop(0)

                if is_speech:
                    # logger.info("Speech detected — recording")
                    speech_started = True
                    frames.extend(pre_buffer)
                    pre_buffer.clear()
                    silence_frames = 0
                else:
                    # CHANGE: speech_start_timeout — give up if nobody speaks
                    waiting_frames += 1
                    if waiting_frames >= speech_start_limit:
                        # logger.info(
                        #     f"No speech detected after {speech_start_timeout_s}s — stopping"
                        # )
                        break

            else:
                # Speech has started — record until silence
                frames.append(raw)

                if is_speech:
                    silence_frames = 0
                else:
                    silence_frames += 1
                    if silence_frames >= silence_limit:
                        # logger.info("Silence detected — stopped")
                        break

    except Exception as e:
        logger.error(f"VAD recording error: {e}", exc_info=True)
        return np.array([])

    finally:
        if stream:
            try:
                stream.stop_stream()
                stream.close()
            except Exception:
                pass
        try:
            pa.terminate()
        except Exception:
            pass

    # ── Convert to float32 numpy array ────────────────────────────────────────
    if not frames:
        logger.warning("No audio recorded (no speech detected)")
        return np.array([])

    audio_bytes = b"".join(frames)
    audio_np    = np.frombuffer(audio_bytes, dtype=np.int16).astype(np.float32) / 32768.0
    duration    = len(audio_np) / sample_rate

    # logger.info(f"VAD recording complete: {len(audio_np)} samples, {duration:.2f}s")
    return audio_np