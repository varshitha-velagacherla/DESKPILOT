# wake word module
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
            model_path = next((p for p in paths if wake_word in p.lower()), None)
            if not model_path:
                available = [os.path.basename(p) for p in paths]
                raise FileNotFoundError(
                    f"'{wake_word}' not found. Available: {available}"
                )

            self._model = WakeWordModel(
                wakeword_model_paths=[model_path],
                enable_speex_noise_suppression=False,
            )

            # Discover output key + warm up model weights
            warmup    = self._model.predict(np.zeros(BLOCK_SAMPLES, dtype=np.int16))
            self._key = next(
                (k for k in warmup if wake_word in k.lower()),
                list(warmup.keys())[0],
            )
            logger.debug(
                f"WakeWordDetector ready — word={wake_word!r} "
                f"key={self._key!r} threshold={self.threshold:.4f}"
            )

        except Exception as e:
            logger.error(f"Failed to initialize WakeWordDetector: {e}", exc_info=True)
            raise

    # ------------------------------------------------------------------ #
    #  Internal helpers                                                    #
    # ------------------------------------------------------------------ #

    def _reset_model_state(self) -> None:
        """
        Reset OpenWakeWord's internal frame buffer so scores from the
        previous listen() session don't bleed into the next one.
        """
        try:
            # openwakeword stores a rolling frame history per model
            for model in self._model.models.values():
                if hasattr(model, "reset"):
                    model.reset()

            # Also zero out the prediction buffer the top-level Model keeps
            if hasattr(self._model, "prediction_buffer"):
                for key in self._model.prediction_buffer:
                    self._model.prediction_buffer[key].clear()
        except Exception:
            # If internal API changes, feed silent frames as fallback
            silence = np.zeros(BLOCK_SAMPLES, dtype=np.int16)
            for _ in range(FLUSH_FRAMES):
                self._model.predict(silence)

    @staticmethod
    def _flush_stream(stream) -> None:
        """Drain stale OS audio buffer right after opening the stream."""
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

    # ------------------------------------------------------------------ #
    #  Public API                                                          #
    # ------------------------------------------------------------------ #

    def listen(self, timeout: int = 30, verbose: bool = True) -> bool:
        """
        Block until wake word is detected or timeout expires.

        Returns:
            True  — wake word detected
            False — timed out
        """
        # ── 1. Inter-call cooldown (prevents instant re-trigger) ──────── #
        MIN_INTERVAL = 3.0
        since_last   = time.time() - self.last_detection_time
        if since_last < MIN_INTERVAL:
            wait = MIN_INTERVAL - since_last
            logger.debug(f"Cooldown: sleeping {wait:.2f}s before listening")
            time.sleep(wait)

        # ── 2. Reset model's internal state ───────────────────────────── #
        self._reset_model_state()

        if verbose:
            print(f"👂 Listening for '{self.wake_word}'... (timeout={timeout}s)")

        # Smoothing window  (5 frames ≈ 400 ms)
        SMOOTH_WIN = 5
        window: list[float] = []
        max_score = 0.0
        start     = time.time()
        tts_skipping = False

        try:
            with sd.InputStream(
                channels=1,
                samplerate=SAMPLE_RATE,
                blocksize=BLOCK_SAMPLES,
                dtype="int16",
            ) as stream:

                # ── 3. Flush OS buffer before processing any audio ─────── #
                self._flush_stream(stream)

                while time.time() - start < timeout:

                    # ── 4. Skip frames while TTS is playing ───────────── #
                    if self._tts_is_speaking():
                        if not tts_skipping:
                            logger.debug("TTS active — pausing wake word detection")
                            tts_skipping = True
                            window.clear()          # discard scores from before TTS
                        stream.read(BLOCK_SAMPLES)  # keep stream alive
                        continue

                    if tts_skipping:
                        logger.debug("TTS finished — resuming wake word detection")
                        tts_skipping = False
                        # Flush any audio captured while TTS was playing
                        self._flush_stream(stream)

                    # ── 5. Read + score ───────────────────────────────── #
                    try:
                        chunk, _ = stream.read(BLOCK_SAMPLES)
                    except Exception as e:
                        logger.warning(f"Stream read error: {e}")
                        continue

                    score = self._model.predict(chunk.flatten())[self._key]
                    max_score = max(max_score, score)

                    # Rolling average
                    window.append(score)
                    if len(window) > SMOOTH_WIN:
                        window.pop(0)
                    smoothed = sum(window) / len(window)

                    if verbose and score > self.threshold * 0.4:
                        print(f"  raw={score:.4f}  smooth={smoothed:.4f}", end="\r")

                    # ── 6. Detection gate ─────────────────────────────── #
                    # Both the smoothed AND instant score must be high enough
                    # to prevent a single noisy spike from triggering.
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