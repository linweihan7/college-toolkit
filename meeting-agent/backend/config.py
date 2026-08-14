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
# Default to "large-v3" — the most accurate model. With a forced language it runs
# a single efficient pass (~0.5x real-time on CPU here, so a 60-min meeting takes
# ~25-35 min). Set LOCAL_WHISPER_MODEL=medium or small to trade accuracy for speed.
LOCAL_WHISPER_MODEL = os.getenv("LOCAL_WHISPER_MODEL", "large-v3")
LOCAL_WHISPER_DEVICE = os.getenv("LOCAL_WHISPER_DEVICE", "cpu")  # cpu | cuda
LOCAL_WHISPER_COMPUTE = os.getenv("LOCAL_WHISPER_COMPUTE", "int8")  # int8 | float32 (more precise, slower) | float16 (GPU)
# Higher beam = more accurate, slower. 5 is a good default; try 8-10 for precision.
LOCAL_WHISPER_BEAM = int(os.getenv("LOCAL_WHISPER_BEAM", "5"))

# Live captions use a small, fast model for low latency; the accurate full pass
# after you stop still uses LOCAL_WHISPER_MODEL (e.g. large-v3).
LIVE_WHISPER_MODEL = os.getenv("LIVE_WHISPER_MODEL", "base")
LIVE_WHISPER_COMPUTE = os.getenv("LIVE_WHISPER_COMPUTE", "int8")

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

# Fast models used for live/whole transcript AI proofreading (low latency).
CLEAN_MODEL_CLAUDE = os.getenv("CLEAN_MODEL_CLAUDE", "claude-haiku-4-5-20251001")
CLEAN_MODEL_OPENAI = os.getenv("CLEAN_MODEL_OPENAI", "gpt-4o-mini")
CLEAN_MODEL_GEMINI = os.getenv("CLEAN_MODEL_GEMINI", "gemini-2.0-flash")

# Meetings are restricted to these two languages by design.
SUPPORTED_LANGUAGES = ("en", "zh")

# This app is Traditional-Chinese-first: recognized Mandarin (which Whisper emits
# as Simplified) is converted to Traditional. s2t = generic; s2twp = Taiwan idioms.
TRADITIONAL_CHINESE = _bool("TRADITIONAL_CHINESE", True)
OPENCC_CONFIG = os.getenv("OPENCC_CONFIG", "s2t")

# --- Serving / access control ------------------------------------------------
# Set APP_PASSWORD to require a login. This is REQUIRED before exposing the app
# beyond localhost — without it, anyone who reaches the URL can read every stored
# meeting. APP_USER defaults to "admin".
APP_USER = os.getenv("APP_USER", "admin")
APP_PASSWORD = os.getenv("APP_PASSWORD", "")

# --- Public multi-user mode --------------------------------------------------
# When on: no password, every visitor gets their own private session and can only
# ever see their own meetings. Run it with a SEPARATE MEETING_DATA_DIR so your
# personal archive is physically absent from the public instance.
PUBLIC_MODE = _bool("PUBLIC_MODE", False)
# Abuse limits (public mode only) — transcription burns CPU on the host machine.
PUBLIC_MAX_UPLOAD_MB = int(os.getenv("PUBLIC_MAX_UPLOAD_MB", "25"))
PUBLIC_MAX_MINUTES = int(os.getenv("PUBLIC_MAX_MINUTES", "10"))
PUBLIC_MAX_PER_HOUR = int(os.getenv("PUBLIC_MAX_PER_HOUR", "5"))

for _d in (DATA_DIR, AUDIO_DIR):
    _d.mkdir(parents=True, exist_ok=True)


def _has_module(name: str) -> bool:
    import importlib.util

    try:
        return importlib.util.find_spec(name) is not None
    except (ImportError, ModuleNotFoundError, ValueError):
        return False


def _confidential() -> bool:
    """Confidential mode: block everything that would send data off the machine."""
    try:
        from . import storage

        return storage.get_setting("confidential_mode", "0") == "1"
    except Exception:  # noqa: BLE001 - settings table may not exist yet
        return False


def capabilities() -> dict:
    """Report which engines/features are actually usable right now."""
    conf = _confidential()
    local_ok = _has_module("faster_whisper")
    diar_pyannote = _has_module("pyannote.audio") and bool(HUGGINGFACE_TOKEN)
    diar_offline = _has_module("resemblyzer") and _has_module("sklearn")
    diar_ok = diar_pyannote or diar_offline
    diar_backend = "pyannote" if diar_pyannote else ("offline" if diar_offline else None)
    return {
        "engines": {
            "local": {
                "available": local_ok,
                "model": LOCAL_WHISPER_MODEL,
                "reason": None if local_ok else "faster-whisper not installed (see requirements-local.txt)",
            },
            "cloud": {
                "available": bool(OPENAI_API_KEY) and _has_module("openai") and not conf,
                "model": OPENAI_TRANSCRIBE_MODEL,
                "reason": "機密模式（僅本機）" if conf
                else (None if (OPENAI_API_KEY and _has_module("openai")) else "OPENAI_API_KEY not set"),
            },
        },
        "diarization": {
            "available": diar_ok,
            "backend": diar_backend,
            "reason": None
            if diar_ok
            else "install resemblyzer + scikit-learn (offline, no key), or pyannote.audio + HUGGINGFACE_TOKEN",
        },
        "summarization": {
            "default": SUMMARY_PROVIDER,
            "providers": {
                "claude": {
                    "available": bool(ANTHROPIC_API_KEY or ANTHROPIC_AUTH_TOKEN) and _has_module("anthropic") and not conf,
                    "model": CLAUDE_MODEL,
                    "reason": "機密模式" if conf else (None if (ANTHROPIC_API_KEY or ANTHROPIC_AUTH_TOKEN) else "ANTHROPIC_API_KEY not set"),
                },
                "openai": {
                    "available": bool(OPENAI_API_KEY) and _has_module("openai") and not conf,
                    "model": OPENAI_SUMMARY_MODEL,
                    "reason": "機密模式" if conf else (None if OPENAI_API_KEY else "OPENAI_API_KEY not set"),
                },
                "gemini": {
                    "available": bool(GEMINI_API_KEY) and _has_module("google.genai") and not conf,
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
        "live": {
            "available": local_ok,
            "model": LIVE_WHISPER_MODEL,
            "reason": None if local_ok else "live captions need faster-whisper (requirements-local.txt)",
        },
        "ffmpeg": shutil.which("ffmpeg") is not None,
        "default_engine": DEFAULT_ENGINE,
        "supported_languages": list(SUPPORTED_LANGUAGES),
        "confidential": conf,
    }


def resolve_summary_provider(preferred: str = "") -> str:
    """Return the requested provider if usable, else fall back to any available
    one (preferred > env default > claude > openai > gemini). "" if none."""
    provs = capabilities()["summarization"]["providers"]
    for p in [preferred, SUMMARY_PROVIDER, "claude", "openai", "gemini", "local"]:
        if p and provs.get(p, {}).get("available"):
            return p
    return ""


def resolve_ai_provider(preferred: str = "") -> str:
    """Like resolve_summary_provider but LLM-only (never the offline summarizer) —
    AI proofreading needs a real model. "" if no AI key is set."""
    provs = capabilities()["summarization"]["providers"]
    for p in [preferred, SUMMARY_PROVIDER, "claude", "openai", "gemini"]:
        if p in ("claude", "openai", "gemini") and provs.get(p, {}).get("available"):
            return p
    return ""
