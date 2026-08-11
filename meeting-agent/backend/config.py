"""Central configuration, loaded from environment / .env.

Everything is optional at import time so the server can boot even when a given
engine's dependencies or keys are missing; capabilities() reports what is
actually usable and the UI adapts to it.
"""
from __future__ import annotations

import os
import shutil
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")


def _bool(name: str, default: bool = False) -> bool:
    return os.getenv(name, str(default)).strip().lower() in {"1", "true", "yes", "on"}


# --- Storage -----------------------------------------------------------------
DATA_DIR = Path(os.getenv("MEETING_DATA_DIR", str(BASE_DIR / "data")))
AUDIO_DIR = DATA_DIR / "audio"
DB_PATH = DATA_DIR / "meetings.db"

# --- Transcription -----------------------------------------------------------
# "local" -> faster-whisper on this machine; "cloud" -> OpenAI transcription API.
DEFAULT_ENGINE = os.getenv("DEFAULT_ENGINE", "local")
LOCAL_WHISPER_MODEL = os.getenv("LOCAL_WHISPER_MODEL", "large-v3")
LOCAL_WHISPER_DEVICE = os.getenv("LOCAL_WHISPER_DEVICE", "cpu")  # cpu | cuda
LOCAL_WHISPER_COMPUTE = os.getenv("LOCAL_WHISPER_COMPUTE", "int8")  # int8 | float16 | float32

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
OPENAI_TRANSCRIBE_MODEL = os.getenv("OPENAI_TRANSCRIBE_MODEL", "whisper-1")
# whisper-1 has a 25 MB upload cap; we chunk cloud audio below this many seconds.
CLOUD_CHUNK_SECONDS = int(os.getenv("CLOUD_CHUNK_SECONDS", "600"))

# --- Speaker diarization -----------------------------------------------------
HUGGINGFACE_TOKEN = os.getenv("HUGGINGFACE_TOKEN", "") or os.getenv("HF_TOKEN", "")
DIARIZATION_MODEL = os.getenv("DIARIZATION_MODEL", "pyannote/speaker-diarization-3.1")

# --- Summarization (pick any: Claude / OpenAI GPT / Google Gemini) -----------
SUMMARY_PROVIDER = os.getenv("SUMMARY_PROVIDER", "claude")  # claude | openai | gemini

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
ANTHROPIC_AUTH_TOKEN = os.getenv("ANTHROPIC_AUTH_TOKEN", "")
CLAUDE_MODEL = os.getenv("CLAUDE_MODEL", "claude-sonnet-5")

OPENAI_SUMMARY_MODEL = os.getenv("OPENAI_SUMMARY_MODEL", "gpt-4o")

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "") or os.getenv("GOOGLE_API_KEY", "")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.0-flash")

# Meetings are restricted to these two languages by design.
SUPPORTED_LANGUAGES = ("en", "zh")

# This app is Traditional-Chinese-first: recognized Mandarin (which Whisper emits
# as Simplified) is converted to Traditional. s2t = generic; s2twp = Taiwan idioms.
TRADITIONAL_CHINESE = _bool("TRADITIONAL_CHINESE", True)
OPENCC_CONFIG = os.getenv("OPENCC_CONFIG", "s2t")

for _d in (DATA_DIR, AUDIO_DIR):
    _d.mkdir(parents=True, exist_ok=True)


def _has_module(name: str) -> bool:
    import importlib.util

    try:
        return importlib.util.find_spec(name) is not None
    except (ImportError, ModuleNotFoundError, ValueError):
        return False


def capabilities() -> dict:
    """Report which engines/features are actually usable right now."""
    local_ok = _has_module("faster_whisper")
    diar_ok = _has_module("pyannote.audio") and bool(HUGGINGFACE_TOKEN)
    return {
        "engines": {
            "local": {
                "available": local_ok,
                "model": LOCAL_WHISPER_MODEL,
                "reason": None if local_ok else "faster-whisper not installed (see requirements-local.txt)",
            },
            "cloud": {
                "available": bool(OPENAI_API_KEY) and _has_module("openai"),
                "model": OPENAI_TRANSCRIBE_MODEL,
                "reason": None if (OPENAI_API_KEY and _has_module("openai")) else "OPENAI_API_KEY not set",
            },
        },
        "diarization": {
            "available": diar_ok,
            "reason": None
            if diar_ok
            else "needs pyannote.audio + HUGGINGFACE_TOKEN (accept model terms on huggingface.co)",
        },
        "summarization": {
            "default": SUMMARY_PROVIDER,
            "providers": {
                "claude": {
                    "available": bool(ANTHROPIC_API_KEY or ANTHROPIC_AUTH_TOKEN) and _has_module("anthropic"),
                    "model": CLAUDE_MODEL,
                    "reason": None if (ANTHROPIC_API_KEY or ANTHROPIC_AUTH_TOKEN) else "ANTHROPIC_API_KEY not set",
                },
                "openai": {
                    "available": bool(OPENAI_API_KEY) and _has_module("openai"),
                    "model": OPENAI_SUMMARY_MODEL,
                    "reason": None if OPENAI_API_KEY else "OPENAI_API_KEY not set",
                },
                "gemini": {
                    "available": bool(GEMINI_API_KEY) and _has_module("google.genai"),
                    "model": GEMINI_MODEL,
                    "reason": None
                    if (GEMINI_API_KEY and _has_module("google.genai"))
                    else "needs GEMINI_API_KEY (or GOOGLE_API_KEY) + google-genai",
                },
                "local": {
                    "available": True,
                    "model": "extractive (offline, no key)",
                    "reason": None,
                },
            },
        },
        "ffmpeg": shutil.which("ffmpeg") is not None,
        "default_engine": DEFAULT_ENGINE,
        "supported_languages": list(SUPPORTED_LANGUAGES),
    }


def resolve_summary_provider(preferred: str = "") -> str:
    """Return the requested provider if usable, else fall back to any available
    one (preferred > env default > claude > openai > gemini). "" if none."""
    provs = capabilities()["summarization"]["providers"]
    for p in [preferred, SUMMARY_PROVIDER, "claude", "openai", "gemini", "local"]:
        if p and provs.get(p, {}).get("available"):
            return p
    return ""
