"""
stt.py — Speech-to-Text + VAD Pipeline, Linux/CPU port

Changes from Windows version:
  1. Whisper model changed: "small" → "base.en" (faster, lower RAM)
  2. Added cpu_threads=4, beam_size=1 for CPU-only performance
  3. VAD device forced to CPU (removed CUDA detection)
  4. Added load-time logging of elapsed time and RSS memory
"""

import numpy as np
import sounddevice as sd
import soundfile as sf
import tempfile
import os
import logging
import time
import torch
import psutil
import pyaudio
from faster_whisper import WhisperModel
from silero_vad import load_silero_vad

logger = logging.getLogger(__name__)

# ── CPU-only device (no CUDA on this machine) ─────────────────────────────────
device = torch.device("cpu")

# ── Whisper STT model — CPU-tuned ────────────────────────────────────────────
# base.en: ~74 MB, ~2–4s transcription for 5s audio on Ryzen 3 3250U
# Change OLLAMA_WHISPER_MODEL in .env to "tiny.en" (faster) or "small.en" (more accurate)
WHISPER_MODEL_SIZE = os.getenv("WHISPER_MODEL", "base.en")

try:
    _t0 = time.time()
    STT_MODEL = WhisperModel(
        WHISPER_MODEL_SIZE,
        device="cpu",
        compute_type="int8",
        cpu_threads=4,       # Use all 4 threads on Ryzen 3 3250U
        num_workers=1,       # One transcription at a time
    )
    _rss = psutil.Process().memory_info().rss // 1024 // 1024
    logger.info(
        f"Whisper STT loaded: model={WHISPER_MODEL_SIZE}, "
        f"device=cpu, compute=int8, "
        f"elapsed={time.time()-_t0:.1f}s, RSS={_rss}MB"
    )
except Exception as e:
    logger.error(f"Failed to load Whisper model: {e}", exc_info=True)
    STT_MODEL = None

SAMPLE_RATE = 16000   # Whisper expects 16kHz

# ── Silero VAD model — CPU ────────────────────────────────────────────────────
try:
    _t0 = time.time()
    vad_model = load_silero_vad().to(device)
    logger.info(f"Silero VAD loaded: device=cpu, elapsed={time.time()-_t0:.1f}s")
except Exception as e:
    logger.error(f"Failed to load VAD model: {e}", exc_info=True)
    vad_model = None


# ══════════════════════════════════════════════════════════════════════════════
# FIXED-DURATION RECORDING  (testing only)
# ══════════════════════════════════════════════════════════════════════════════

def record_audio(duration: int = 5, sample_rate: int = SAMPLE_RATE) -> np.ndarray:
    """Record audio for a fixed duration. Use record_until_silence() in production."""
    try:
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
    Transcribe a numpy audio array using faster-whisper (CPU / int8).
    Returns transcribed text, or "" on failure.
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

        segments, info = STT_MODEL.transcribe(
            tmp_path,
            language="en",
            beam_size=1,              # fastest on CPU; was unset (default=5)
            vad_filter=True,
            vad_parameters=dict(min_silence_duration_ms=500)
        )
        text = " ".join(seg.text for seg in segments).strip()

        logger.debug(f"Transcription done in {time.time()-t0:.2f}s: '{text}'")
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
    sample_rate:            int   = SAMPLE_RATE,
    speech_start_timeout_s: int   = 5,
    silence_threshold_ms:   int   = 2000,
    max_duration_s:         int   = 10,
    speech_threshold:       float = 0.5,
    pre_buffer_max_s:       float = 0.5,
) -> np.ndarray:
    """
    Record audio from mic until silence (Silero VAD).
    All parameters same as original; no functional change on Linux.
    """
    if vad_model is None:
        logger.error("VAD model not loaded — cannot record")
        return np.array([])

    frame_duration_ms     = 32
    frame_size            = int(sample_rate * frame_duration_ms / 1000)  # 512 samples

    silence_limit         = int(silence_threshold_ms   / frame_duration_ms)
    speech_start_limit    = int(speech_start_timeout_s * 1000 / frame_duration_ms)
    max_frames            = int(max_duration_s         * 1000 / frame_duration_ms)
    pre_buffer_max_frames = int(pre_buffer_max_s       * 1000 / frame_duration_ms)

    try:
        from src.wpa.voice.tts import get_speaking_status as _tts_status
    except ImportError:
        _tts_status = None

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

        frames         = []
        pre_buffer     = []
        silence_frames = 0
        speech_started = False
        waiting_frames = 0

        for _ in range(max_frames):

            if _tts_status is not None:
                try:
                    if _tts_status():
                        stream.read(frame_size, exception_on_overflow=False)
                        continue
                except Exception:
                    pass

            try:
                raw = stream.read(frame_size, exception_on_overflow=False)
            except Exception as e:
                logger.warning(f"Stream read error: {e}")
                continue

            audio_f32    = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
            audio_tensor = torch.from_numpy(audio_f32).unsqueeze(0).to(device)

            with torch.no_grad():
                speech_prob = vad_model(audio_tensor, sample_rate).item()

            is_speech = speech_prob > speech_threshold

            if not speech_started:
                pre_buffer.append(raw)
                if len(pre_buffer) > pre_buffer_max_frames:
                    pre_buffer.pop(0)

                if is_speech:
                    speech_started = True
                    frames.extend(pre_buffer)
                    pre_buffer.clear()
                    silence_frames = 0
                else:
                    waiting_frames += 1
                    if waiting_frames >= speech_start_limit:
                        break
            else:
                frames.append(raw)
                if is_speech:
                    silence_frames = 0
                else:
                    silence_frames += 1
                    if silence_frames >= silence_limit:
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

    if not frames:
        logger.warning("No audio recorded (no speech detected)")
        return np.array([])

    audio_bytes = b"".join(frames)
    audio_np    = np.frombuffer(audio_bytes, dtype=np.int16).astype(np.float32) / 32768.0
    return audio_np