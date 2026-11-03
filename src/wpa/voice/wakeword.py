"""
wakeword.py — Linux port

Changes from Windows version:
  - Added inference_framework="onnx" to WakeWordModel constructor.
    tflite is unavailable on Python 3.11; onnx works on all platforms.
  - No other changes — openwakeword is cross-platform once onnx is forced.
"""

import os
import time
import logging
import numpy as np
import sounddevice as sd
from openwakeword import get_pretrained_model_paths
from openwakeword.model import Model as WakeWordModel

logger = logging.getLogger(__name__)

BLOCK_SAMPLES = 1280
SAMPLE_RATE   = 16000
FLUSH_FRAMES  = 30   # ~2.4s of audio to drain from buffer on stream open


class WakeWordDetector:
    """
    Loads model once, reusable across multiple listen() calls.
    Instantiate once at app startup, call .listen() in a loop.
    """

    def __init__(self, wake_word: str = "alexa", threshold: float = 0.6):
        self.wake_word           = wake_word
        self.threshold           = threshold
        self.last_detection_time = 0.0

        try:
            paths      = get_pretrained_model_paths()
            # get_pretrained_model_paths() returns .tflite paths.
            # We need the .onnx equivalent for Python 3.11 (no tflite runtime).
            tflite_path = next((p for p in paths if wake_word in p.lower()), None)
            if not tflite_path:
                available = [os.path.basename(p) for p in paths]
                raise FileNotFoundError(
                    f"'{wake_word}' not found. Available: {available}"
                )
            # Swap extension to .onnx
            model_path  = tflite_path.replace(".tflite", ".onnx")
            if not os.path.exists(model_path):
                raise FileNotFoundError(
                    f"ONNX model not found at {model_path}. "
                    "Run: python -c \"from openwakeword.utils import download_models; download_models()\""
                )

            self._model = WakeWordModel(
                wakeword_models=[model_path],   # new API (replaces wakeword_model_paths)
                enable_speex_noise_suppression=False,
                inference_framework="onnx",     # tflite unavailable on Python 3.11
            )

            # Discover output key + warm up model weights
            warmup    = self._model.predict(np.zeros(BLOCK_SAMPLES, dtype=np.int16))
            self._key = next(
                (k for k in warmup if wake_word in k.lower()),
                list(warmup.keys())[0],
            )
            logger.info(
                f"WakeWordDetector ready — word={wake_word!r} "
                f"key={self._key!r} threshold={self.threshold:.4f} "
                f"backend=onnx"
            )

        except Exception as e:
            logger.error(f"Failed to initialize WakeWordDetector: {e}", exc_info=True)
            raise

    def _reset_model_state(self) -> None:
        try:
            for model in self._model.models.values():
                if hasattr(model, "reset"):
                    model.reset()
            if hasattr(self._model, "prediction_buffer"):
                for key in self._model.prediction_buffer:
                    self._model.prediction_buffer[key].clear()
        except Exception:
            silence = np.zeros(BLOCK_SAMPLES, dtype=np.int16)
            for _ in range(FLUSH_FRAMES):
                self._model.predict(silence)

    @staticmethod
    def _flush_stream(stream) -> None:
        for _ in range(FLUSH_FRAMES):
            try:
                stream.read(BLOCK_SAMPLES)
            except Exception:
                break

    def _tts_is_speaking(self) -> bool:
        try:
            from src.wpa.voice.tts import get_speaking_status
            return get_speaking_status()
        except Exception:
            return False

    def listen(self, timeout: int = 30, verbose: bool = True) -> bool:
        """
        Block until wake word is detected or timeout expires.
        Returns True (detected) or False (timed out).
        """
        MIN_INTERVAL = 3.0
        since_last   = time.time() - self.last_detection_time
        if since_last < MIN_INTERVAL:
            time.sleep(MIN_INTERVAL - since_last)

        self._reset_model_state()

        if verbose:
            print(f"👂 Listening for '{self.wake_word}'... (timeout={timeout}s)")

        SMOOTH_WIN   = 5
        window: list[float] = []
        max_score    = 0.0
        start        = time.time()
        tts_skipping = False

        try:
            with sd.InputStream(
                channels=1,
                samplerate=SAMPLE_RATE,
                blocksize=BLOCK_SAMPLES,
                dtype="int16",
            ) as stream:

                self._flush_stream(stream)

                while time.time() - start < timeout:

                    if self._tts_is_speaking():
                        if not tts_skipping:
                            tts_skipping = True
                            window.clear()
                        stream.read(BLOCK_SAMPLES)
                        continue

                    if tts_skipping:
                        tts_skipping = False
                        self._flush_stream(stream)

                    try:
                        chunk, _ = stream.read(BLOCK_SAMPLES)
                    except Exception as e:
                        logger.warning(f"Stream read error: {e}")
                        continue

                    score     = self._model.predict(chunk.flatten())[self._key]
                    max_score = max(max_score, score)

                    window.append(score)
                    if len(window) > SMOOTH_WIN:
                        window.pop(0)
                    smoothed = sum(window) / len(window)

                    if verbose and score > self.threshold * 0.4:
                        print(f"  raw={score:.4f}  smooth={smoothed:.4f}", end="\r")

                    if smoothed >= self.threshold and score >= self.threshold * 0.85:
                        self.last_detection_time = time.time()
                        if verbose:
                            print(f"\n🟢 Detected! raw={score:.4f} smooth={smoothed:.4f}")
                        return True

        except Exception as e:
            logger.error(f"Audio stream error: {e}", exc_info=True)
            return False

        if verbose:
            print(f"\n⏰ Timeout — max score: {max_score:.4f} (threshold: {self.threshold:.4f})")
        return False