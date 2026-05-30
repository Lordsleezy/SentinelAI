"""voice_io.py — Speech-to-text and text-to-speech for SentinelAI.

Everything here degrades gracefully. If no STT/TTS backend is installed, the
functions return structured "unavailable" results and the HUD falls back to
text-only interaction (HARD RULE).

STT preference order:  faster-whisper  ->  SpeechRecognition (needs wav)  ->  unavailable
TTS preference order:  pyttsx3  ->  unavailable  (browser SpeechSynthesis covers the rest)
"""
from __future__ import annotations

import logging
import os
import tempfile
import wave
from typing import Optional

logger = logging.getLogger(__name__)

_whisper_model = None


# ─── Capability probes ────────────────────────────────────────────────────────

def _have(mod: str) -> bool:
    try:
        __import__(mod)
        return True
    except Exception:
        return False


def stt_backend() -> str:
    if _have("faster_whisper"):
        return "faster-whisper"
    if _have("speech_recognition"):
        return "speech_recognition"
    return "unavailable"


def tts_backend() -> str:
    if _have("pyttsx3"):
        return "pyttsx3"
    return "unavailable"


def capabilities() -> dict:
    return {
        "stt": stt_backend(),
        "tts": tts_backend(),
        "ffmpeg": _ffmpeg_available(),
    }


def _ffmpeg_available() -> bool:
    from shutil import which
    return which("ffmpeg") is not None


# ─── webm/ogg -> wav (best effort) ─────────────────────────────────────────────

def _to_wav(src_path: str) -> Optional[str]:
    """Convert an arbitrary audio file to 16k mono wav. Returns path or None."""
    # Try pydub (which itself needs ffmpeg) — only if ffmpeg exists.
    if _ffmpeg_available() and _have("pydub"):
        try:
            from pydub import AudioSegment
            seg = AudioSegment.from_file(src_path)
            seg = seg.set_frame_rate(16000).set_channels(1)
            out = src_path + ".wav"
            seg.export(out, format="wav")
            return out
        except Exception as exc:
            logger.warning("pydub conversion failed: %s", exc)
    # If the file is already a wav, use it directly.
    if src_path.lower().endswith(".wav"):
        return src_path
    return None


# ─── STT ───────────────────────────────────────────────────────────────────────

def transcribe(audio_path: str) -> dict:
    """Transcribe an audio file. Returns {ok, text, backend, error}."""
    backend = stt_backend()
    if backend == "unavailable":
        return {"ok": False, "text": "", "backend": "unavailable",
                "error": "no STT backend installed (faster-whisper / SpeechRecognition)"}

    if backend == "faster-whisper":
        try:
            global _whisper_model
            from faster_whisper import WhisperModel
            if _whisper_model is None:
                _whisper_model = WhisperModel("base", device="cpu", compute_type="int8")
            segments, _ = _whisper_model.transcribe(audio_path)
            text = " ".join(seg.text for seg in segments).strip()
            return {"ok": True, "text": text, "backend": backend, "error": None}
        except Exception as exc:
            logger.warning("faster-whisper failed: %s", exc)
            # fall through to SpeechRecognition if available

    if _have("speech_recognition"):
        wav = _to_wav(audio_path)
        if not wav:
            return {"ok": False, "text": "", "backend": "speech_recognition",
                    "error": "audio not in wav and ffmpeg/pydub unavailable for conversion"}
        try:
            import speech_recognition as sr
            recog = sr.Recognizer()
            with sr.AudioFile(wav) as source:
                audio = recog.record(source)
            text = recog.recognize_google(audio)  # online; falls back to error offline
            return {"ok": True, "text": text, "backend": "speech_recognition", "error": None}
        except Exception as exc:
            return {"ok": False, "text": "", "backend": "speech_recognition", "error": str(exc)}

    return {"ok": False, "text": "", "backend": "unavailable", "error": "no usable STT path"}


# ─── TTS ─────────────────────────────────────────────────────────────────────

def synthesize(text: str, out_path: Optional[str] = None) -> dict:
    """Render text to a wav file. Returns {ok, path, backend, error}."""
    if not text:
        return {"ok": False, "path": None, "backend": tts_backend(), "error": "empty text"}
    backend = tts_backend()
    if backend == "pyttsx3":
        try:
            import pyttsx3
            out_path = out_path or os.path.join(tempfile.gettempdir(), "sentinel_tts.wav")
            engine = pyttsx3.init()
            engine.save_to_file(text, out_path)
            engine.runAndWait()
            return {"ok": True, "path": out_path, "backend": backend, "error": None}
        except Exception as exc:
            return {"ok": False, "path": None, "backend": backend, "error": str(exc)}
    return {"ok": False, "path": None, "backend": "unavailable",
            "error": "no TTS backend; use browser SpeechSynthesis fallback"}
