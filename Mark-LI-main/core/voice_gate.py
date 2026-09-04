"""Local, best-effort gate for the Gemini Live microphone.

The gate deliberately fails closed when it is enabled but a wake-word model,
speaker model, or enrolled profile is unavailable.  It stores an embedding
only; enrollment audio is never written to disk or sent to Gemini.

This is not biometric security.  Resemblyzer is a convenience, local speaker
similarity check and should not be used as an access-control system.
"""

from __future__ import annotations

import importlib.util
import json
import math
import os
import threading
import time
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

DEFAULT_WAKE_WORD = "ADHITHIYA"
DEFAULT_PROFILE_PATH = Path.home() / ".adhithiya" / "voice_profile.json"
_DEFAULT_THRESHOLD = 0.70
_MIN_ENROLL_SECONDS = 1.0
_MIN_VERIFY_SECONDS = 0.8


def _normalise_wake_word(value: Any) -> str:
    value = str(value or DEFAULT_WAKE_WORD).strip()
    return " ".join(value.split()).upper() or DEFAULT_WAKE_WORD


@dataclass(frozen=True)
class VoiceGateConfig:
    enabled: bool = False
    wake_word_enabled: bool = True
    wake_word: str = DEFAULT_WAKE_WORD
    profile_path: Path = DEFAULT_PROFILE_PATH
    wake_model_path: Path | None = None
    wake_backend: str = "auto"
    porcupine_access_key: str | None = None
    speaker_threshold: float = _DEFAULT_THRESHOLD
    wake_timeout_seconds: float = 20.0
    verify_seconds: float = 1.5
    sample_rate: int = 16_000
    wake_threshold: float = 0.5

    @classmethod
    def from_mapping(cls, config: dict[str, Any] | None) -> "VoiceGateConfig":
        config = config if isinstance(config, dict) else {}
        raw_profile = (
            os.environ.get("ADHITHIYA_VOICE_PROFILE")
            or config.get("voice_profile_path")
            or str(DEFAULT_PROFILE_PATH)
        )
        raw_model = config.get("wake_word_model_path")
        try:
            threshold = float(config.get("voice_similarity_threshold", _DEFAULT_THRESHOLD))
        except (TypeError, ValueError):
            threshold = _DEFAULT_THRESHOLD
        try:
            timeout = float(config.get("voice_wake_timeout_seconds", 20.0))
        except (TypeError, ValueError):
            timeout = 20.0
        try:
            verify_seconds = float(config.get("voice_verify_seconds", 1.5))
        except (TypeError, ValueError):
            verify_seconds = 1.5
        try:
            wake_threshold = float(config.get("wake_word_threshold", 0.5))
        except (TypeError, ValueError):
            wake_threshold = 0.5
        return cls(
            enabled=bool(config.get("voice_lock_enabled", False)),
            wake_word_enabled=bool(config.get("wake_word_enabled", True)),
            wake_word=_normalise_wake_word(config.get("wake_word", DEFAULT_WAKE_WORD)),
            profile_path=Path(str(raw_profile)).expanduser(),
            wake_model_path=Path(str(raw_model)).expanduser() if raw_model else None,
            wake_backend=str(config.get("wake_word_backend", "auto")).strip().lower() or "auto",
            porcupine_access_key=(
                str(config["porcupine_access_key"]).strip()
                if config.get("porcupine_access_key")
                else None
            ),
            speaker_threshold=min(max(threshold, 0.0), 1.0),
            wake_timeout_seconds=max(timeout, 2.0),
            verify_seconds=max(verify_seconds, _MIN_VERIFY_SECONDS),
            sample_rate=16_000,
            wake_threshold=min(max(wake_threshold, 0.05), 0.99),
        )


class VoiceProfileStore:
    """Read/write an embedding profile outside the source tree."""

    def __init__(self, path: Path = DEFAULT_PROFILE_PATH):
        self.path = Path(path).expanduser()

    def load(self) -> dict[str, Any] | None:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return None
        except (OSError, json.JSONDecodeError) as exc:
            raise ValueError(f"Voice profile cannot be read: {exc}") from exc
        embedding = data.get("embedding") if isinstance(data, dict) else None
        if not isinstance(embedding, list) or len(embedding) < 8:
            raise ValueError("Voice profile is invalid (embedding is missing).")
        try:
            if not all(math.isfinite(float(x)) for x in embedding):
                raise ValueError("Voice profile contains non-finite values.")
        except (TypeError, ValueError) as exc:
            raise ValueError("Voice profile contains invalid values.") from exc
        return data

    def save(self, embedding: Any, *, model: str = "resemblyzer") -> None:
        values = [float(x) for x in embedding]
        if len(values) < 8 or not all(math.isfinite(x) for x in values):
            raise ValueError("The local speaker model returned an invalid embedding.")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "version": 1,
            "model": model,
            "embedding": values,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "note": "Embedding metadata only; raw enrollment audio is not stored.",
        }
        temporary = self.path.with_name(f".{self.path.name}.new")
        temporary.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        try:
            os.chmod(temporary, 0o600)
        except OSError:
            pass
        temporary.replace(self.path)
        try:
            os.chmod(self.path, 0o600)
        except OSError:
            pass

    def status(self) -> str:
        try:
            return "enrolled" if self.load() else "not_enrolled"
        except ValueError:
            return "invalid"


class _SpeakerModel:
    """Lazy Resemblyzer wrapper. Import/model loading never happens at startup."""

    def __init__(self):
        self._encoder = None
        self._lock = threading.Lock()

    @staticmethod
    def available() -> bool:
        return importlib.util.find_spec("resemblyzer") is not None

    def _get_encoder(self):
        with self._lock:
            if self._encoder is None:
                try:
                    from resemblyzer import VoiceEncoder
                except ImportError as exc:
                    raise RuntimeError(
                        "Local speaker verification is unavailable. "
                        "Install the optional 'resemblyzer' package, then enroll a profile."
                    ) from exc
                self._encoder = VoiceEncoder()
            return self._encoder

    @staticmethod
    def _samples(audio: bytes, sample_rate: int) -> Any:
        try:
            import numpy as np
        except ImportError as exc:
            raise RuntimeError("Speaker verification needs numpy.") from exc
        values = np.frombuffer(audio, dtype=np.int16).astype(np.float32) / 32768.0
        if values.size < int(sample_rate * _MIN_VERIFY_SECONDS):
            raise ValueError("Not enough speech yet for local speaker verification.")
        return values

    def embed(self, audio: bytes, sample_rate: int = 16_000) -> list[float]:
        samples = self._samples(audio, sample_rate)
        embedding = self._get_encoder().embed_utterance(samples)
        return [float(x) for x in embedding]


class _OpenWakeWord:
    def __init__(self, path: Path, threshold: float):
        try:
            from openwakeword.model import Model
        except ImportError as exc:
            raise RuntimeError(
                "OpenWakeWord is unavailable. Install 'openwakeword' or configure an offline Vosk model."
            ) from exc
        if not path.is_file():
            raise RuntimeError(
                f"Wake-word model not found at {path}. No model was downloaded automatically."
            )
        self._threshold = threshold
        try:
            self._model = Model(wakeword_models=[str(path)])
        except (OSError, ValueError, RuntimeError, TypeError, KeyError) as exc:
            raise RuntimeError(f"Could not load the local wake-word model: {exc}") from exc

    def process(self, audio: bytes) -> bool:
        import numpy as np

        scores = self._model.predict(np.frombuffer(audio, dtype=np.int16))
        return any(float(score) >= self._threshold for score in scores.values())


class _VoskWakeWord:
    def __init__(self, model_path: Path, wake_word: str):
        try:
            from vosk import KaldiRecognizer, Model
        except ImportError as exc:
            raise RuntimeError(
                "Vosk is unavailable. Install optional 'vosk' and configure wake_word_model_path."
            ) from exc
        if not model_path.is_dir():
            raise RuntimeError(f"Vosk model directory not found at {model_path}.")
        self._wake_word = _normalise_wake_word(wake_word).lower()
        self._recognizer = KaldiRecognizer(Model(str(model_path)), 16_000)

    def process(self, audio: bytes) -> bool:
        import json as _json

        if self._recognizer.AcceptWaveform(audio):
            result = _json.loads(self._recognizer.Result())
        else:
            result = _json.loads(self._recognizer.PartialResult())
        return self._wake_word in str(result.get("text") or result.get("partial") or "").lower()


class _PorcupineWakeWord:
    def __init__(self, access_key: str, keyword_path: Path):
        try:
            import pvporcupine
        except ImportError as exc:
            raise RuntimeError(
                "Porcupine is unavailable. Install optional 'pvporcupine' or configure Vosk/openWakeWord."
            ) from exc
        if not keyword_path.is_file():
            raise RuntimeError(f"Porcupine keyword model not found at {keyword_path}.")
        try:
            self._porcupine = pvporcupine.create(
                access_key=access_key,
                keyword_paths=[str(keyword_path)],
            )
        except (OSError, ValueError, RuntimeError, TypeError, KeyError) as exc:
            raise RuntimeError(f"Could not load the local Porcupine model: {exc}") from exc
        self._pending = bytearray()

    def process(self, audio: bytes) -> bool:
        import numpy as np

        self._pending.extend(audio)
        frame_bytes = self._porcupine.frame_length * 2
        detected = False
        while len(self._pending) >= frame_bytes:
            frame = np.frombuffer(self._pending[:frame_bytes], dtype=np.int16)
            del self._pending[:frame_bytes]
            if self._porcupine.process(frame) >= 0:
                detected = True
        return detected

    def close(self) -> None:
        self._porcupine.delete()


def _wake_model_path(config: VoiceGateConfig) -> Path | None:
    if config.wake_model_path:
        return config.wake_model_path
    # openWakeWord ships no model files in many installations.  Only use a
    # matching file if it is already present; never call download_models().
    try:
        import openwakeword

        aliases = {
            "HEY ADHITHIYA": "hey_jarvis",
            "HEY MYCROFT": "hey_mycroft",
            "HEY RHASSPY": "hey_rhasspy",
            "ALEXA": "alexa",
        }
        model_name = aliases.get(config.wake_word)
        if model_name:
            candidate = Path(openwakeword.__file__).parent / "resources" / "models" / f"{model_name}_v0.1.tflite"
            return candidate
    except ImportError:
        return None
    return None


@dataclass(frozen=True)
class VoiceGateDecision:
    accepted: bool
    state: str
    message: str | None = None


class VoiceGate:
    """Non-blocking microphone gate used by the Live audio callback."""

    def __init__(self, config: VoiceGateConfig, logger: Callable[[str], None] | None = None):
        self.config = config
        self.profile_store = VoiceProfileStore(config.profile_path)
        self._logger = logger or (lambda _message: None)
        self._detector = None
        self._detector_error: str | None = None
        self._speaker = _SpeakerModel()
        self._executor: ThreadPoolExecutor | None = None
        self._future: Future[bool] | None = None
        self._state = "disabled" if not config.enabled else "waiting_wake"
        self._buffer = bytearray()
        self._active_until = 0.0
        self._verification_started = 0.0
        self._last_notice: str | None = None
        self._profile_status = "not_enrolled"
        self._profile_checked_at = 0.0
        self._lock = threading.Lock()

    @classmethod
    def from_config_path(cls, path: Path, logger: Callable[[str], None] | None = None) -> "VoiceGate":
        try:
            config = json.loads(Path(path).read_text(encoding="utf-8"))
        except FileNotFoundError:
            config = {}
        except (OSError, json.JSONDecodeError) as exc:
            raise ValueError(f"Cannot load voice configuration: {exc}") from exc
        return cls(VoiceGateConfig.from_mapping(config), logger=logger)

    def status(self) -> dict[str, Any]:
        now = time.monotonic()
        if now - self._profile_checked_at >= 1.0:
            self._profile_status = self.profile_store.status()
            self._profile_checked_at = now
        profile_status = self._profile_status
        setup = self._detector_error
        if self.config.enabled and profile_status != "enrolled":
            setup = (
                f"Voice lock is enabled but no valid profile is enrolled. "
                f"Run enroll_voice_profile(...) using local audio; profile path: {self.profile_store.path}"
            )
        elif self.config.enabled and not self._speaker.available():
            setup = (
                "Voice lock is enabled but Resemblyzer is not installed. "
                "Install the optional 'resemblyzer' package and enroll a profile."
            )
        return {
            "enabled": self.config.enabled,
            "wake_word_enabled": self.config.wake_word_enabled,
            "wake_word": self.config.wake_word,
            "profile_status": profile_status,
            "profile_path": str(self.profile_store.path),
            "state": self._state,
            "setup_message": setup,
        }

    def _notice(self, message: str) -> str | None:
        if message == self._last_notice:
            return None
        self._last_notice = message
        self._logger(message)
        return message

    def _get_detector(self):
        if not self.config.wake_word_enabled:
            return None
        if self._detector is not None or self._detector_error:
            return self._detector
        path = _wake_model_path(self.config)
        try:
            if self.config.wake_backend in {"vosk"} or (
                self.config.wake_backend == "auto" and path and path.is_dir()
            ):
                self._detector = _VoskWakeWord(path, self.config.wake_word) if path else None
            elif self.config.wake_backend == "porcupine":
                if not self.config.porcupine_access_key:
                    raise RuntimeError(
                        "Porcupine requires a configured access key and keyword model; no key was used automatically."
                    )
                if not path:
                    raise RuntimeError("Configure a .ppn model path in wake_word_model_path for Porcupine.")
                self._detector = _PorcupineWakeWord(self.config.porcupine_access_key, path)
            elif path:
                self._detector = _OpenWakeWord(path, self.config.wake_threshold)
            else:
                raise RuntimeError(
                    f"No offline wake-word model is available for '{self.config.wake_word}'. "
                    "Configure wake_word_model_path (openWakeWord/Vosk), or disable wake_word_enabled."
                )
        except RuntimeError as exc:
            self._detector_error = str(exc)
        return self._detector

    def _begin_verification(self) -> None:
        self._state = "verifying"
        self._verification_started = time.monotonic()
        self._buffer.clear()
        if self._executor is None:
            self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="voice-verify")

    def _verify(self, audio: bytes) -> bool:
        profile = self.profile_store.load()
        if not profile:
            return False
        candidate = self._speaker.embed(audio, self.config.sample_rate)
        try:
            import numpy as np
        except ImportError as exc:
            raise RuntimeError("Speaker verification needs numpy.") from exc
        stored = np.asarray(profile["embedding"], dtype=np.float32)
        current = np.asarray(candidate, dtype=np.float32)
        if stored.shape != current.shape:
            raise ValueError("Enrolled profile was created with an incompatible speaker model.")
        denominator = float(np.linalg.norm(stored) * np.linalg.norm(current))
        similarity = float(np.dot(stored, current) / denominator) if denominator else 0.0
        return similarity >= self.config.speaker_threshold

    def process_audio(self, audio: bytes) -> VoiceGateDecision:
        """Process one 16-bit/16 kHz mono chunk without sending it anywhere."""
        if not self.config.enabled:
            return VoiceGateDecision(True, "disabled")
        if not isinstance(audio, (bytes, bytearray, memoryview)):
            raise TypeError("Voice gate audio must be PCM bytes.")
        audio = bytes(audio)
        now = time.monotonic()
        if now - self._profile_checked_at >= 1.0:
            self._profile_status = self.profile_store.status()
            self._profile_checked_at = now
        profile_status = self._profile_status
        if profile_status != "enrolled":
            message = (
                f"Voice lock is enabled but profile status is '{profile_status}'. "
                f"Enroll locally with enroll_voice_profile(...); no audio was sent."
            )
            return VoiceGateDecision(False, "setup_required", self._notice(message))
        if not self._speaker.available():
            message = (
                "Voice lock is enabled, but local speaker verification is unavailable. "
                "Install 'resemblyzer' and enroll a profile; no audio was sent."
            )
            return VoiceGateDecision(False, "setup_required", self._notice(message))
        detector = self._get_detector()
        if self.config.wake_word_enabled and detector is None:
            message = self._detector_error or "Wake-word detector is unavailable; no audio was sent."
            return VoiceGateDecision(False, "setup_required", self._notice(message))
        with self._lock:
            if self._state == "active":
                if now < self._active_until:
                    return VoiceGateDecision(True, "active")
                self._state = "waiting_wake"
                self._buffer.clear()
            if self._state == "waiting_wake":
                detected = (
                    detector.process(audio)
                    if detector is not None
                    else self._energy(audio) >= 0.01
                )
                if detected:
                    self._begin_verification()
                    message = self._notice(
                        f"Wake word detected. Verifying speaker locally before opening the microphone ({self.config.wake_word})."
                    )
                    return VoiceGateDecision(False, "verifying", message)
                return VoiceGateDecision(False, "waiting_wake")
            if self._state == "verifying":
                if now > self._verification_started + self.config.wake_timeout_seconds:
                    self._future = None
                    self._state = "waiting_wake"
                    self._buffer.clear()
                    return VoiceGateDecision(
                        False,
                        "wake_timeout",
                        self._notice("Wake verification timed out; say the wake word and try again."),
                    )
                self._buffer.extend(audio)
                max_bytes = int(self.config.sample_rate * 2 * min(self.config.wake_timeout_seconds, 8.0))
                if len(self._buffer) > max_bytes:
                    self._buffer = self._buffer[-max_bytes:]
                needed = int(self.config.sample_rate * 2 * self.config.verify_seconds)
                if self._future is None and len(self._buffer) >= needed:
                    self._future = self._executor.submit(self._verify, bytes(self._buffer))
                if self._future is None or not self._future.done():
                    return VoiceGateDecision(False, "verifying")
                try:
                    verified = self._future.result()
                except (RuntimeError, ValueError) as exc:
                    self._future = None
                    self._state = "waiting_wake"
                    self._buffer.clear()
                    return VoiceGateDecision(False, "verification_unavailable", self._notice(str(exc)))
                self._future = None
                self._buffer.clear()
                if verified:
                    self._state = "active"
                    self._active_until = now + self.config.wake_timeout_seconds
                    return VoiceGateDecision(False, "verified", self._notice("Speaker verified locally; microphone opened."))
                self._state = "waiting_wake"
                return VoiceGateDecision(False, "speaker_rejected", self._notice("Speaker was not verified; say the wake word and try again."))
        return VoiceGateDecision(False, "waiting_wake")

    @staticmethod
    def _energy(audio: bytes) -> float:
        try:
            import numpy as np

            samples = np.frombuffer(audio, dtype=np.int16).astype(np.float32)
            return float(np.sqrt(np.mean(np.square(samples))) / 32768.0) if samples.size else 0.0
        except ImportError:
            return 0.0

    def close(self) -> None:
        detector = self._detector
        if hasattr(detector, "close"):
            detector.close()
        if self._executor:
            self._executor.shutdown(wait=False, cancel_futures=True)
            self._executor = None


def enroll_voice_profile(
    audio: bytes,
    *,
    sample_rate: int = 16_000,
    profile_path: str | Path | None = None,
    replace: bool = False,
) -> dict[str, Any]:
    """Enroll one local speaker embedding from PCM audio.

    ``audio`` must be 16-bit mono PCM.  Existing profiles are not overwritten
    unless ``replace=True``.  This function never stores the supplied audio.
    """
    store = VoiceProfileStore(Path(profile_path).expanduser() if profile_path else DEFAULT_PROFILE_PATH)
    if store.status() == "enrolled" and not replace:
        raise FileExistsError(f"A voice profile already exists at {store.path}; pass replace=True to replace it.")
    if len(audio) < int(sample_rate * 2 * _MIN_ENROLL_SECONDS):
        raise ValueError("Enrollment needs at least one second of local PCM speech.")
    embedding = _SpeakerModel().embed(bytes(audio), sample_rate)
    store.save(embedding)
    return {
        "status": "enrolled",
        "profile_path": str(store.path),
        "model": "resemblyzer",
        "raw_audio_stored": False,
    }


def voice_profile_status(profile_path: str | Path | None = None) -> str:
    """Return ``not_enrolled``, ``enrolled`` or ``invalid``."""
    return VoiceProfileStore(Path(profile_path).expanduser() if profile_path else DEFAULT_PROFILE_PATH).status()


def clear_voice_profile(profile_path: str | Path | None = None) -> None:
    """Delete the local embedding profile, never any audio recording."""
    path = VoiceProfileStore(Path(profile_path).expanduser() if profile_path else DEFAULT_PROFILE_PATH).path
    try:
        path.unlink()
    except FileNotFoundError:
        return


def _cli() -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Manage ADHITHIYA's local voice profile.")
    parser.add_argument("command", choices=("enroll", "status", "clear"))
    parser.add_argument("--seconds", type=float, default=5.0, help="Enrollment recording length (default: 5s).")
    parser.add_argument("--profile", default=None, help="Optional profile path (default: ~/.adhithiya/voice_profile.json).")
    parser.add_argument("--replace", action="store_true", help="Replace an existing profile.")
    args = parser.parse_args()
    if args.command == "status":
        print(voice_profile_status(args.profile))
        return 0
    if args.command == "clear":
        clear_voice_profile(args.profile)
        print("Voice profile cleared.")
        return 0
    if args.seconds < _MIN_ENROLL_SECONDS:
        parser.error(f"--seconds must be at least {_MIN_ENROLL_SECONDS:g}")
    try:
        import sounddevice as sd
    except ImportError as exc:
        parser.error(f"Enrollment recording needs sounddevice: {exc}")
    import numpy as np

    print(f"Speak naturally for {args.seconds:g} seconds. Audio stays in memory and is not saved.")
    recording = sd.rec(
        int(args.seconds * 16_000),
        samplerate=16_000,
        channels=1,
        dtype="int16",
    )
    sd.wait()
    result = enroll_voice_profile(
        np.asarray(recording).reshape(-1).tobytes(),
        profile_path=args.profile,
        replace=args.replace,
    )
    print(f"Enrolled local speaker profile at {result['profile_path']}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(_cli())
