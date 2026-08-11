"""Convert Mandarin transcription output to Traditional Chinese.

Whisper (and the cloud API) emit Simplified Chinese for Mandarin. This app is
Traditional-Chinese-first, so we run recognized text through OpenCC. Only Han
characters are affected — English / numbers / punctuation pass through untouched,
so it is safe to apply to mixed EN+中文 meetings.

If OpenCC is not installed the text is returned unchanged.
"""
from __future__ import annotations

from typing import List

from . import config

_cc = None  # None = not tried, False = unavailable, else an OpenCC instance


def _converter():
    global _cc
    if _cc is None:
        try:
            from opencc import OpenCC

            _cc = OpenCC(config.OPENCC_CONFIG)
        except Exception:
            _cc = False
    return _cc


def to_traditional(text: str) -> str:
    if not config.TRADITIONAL_CHINESE or not text:
        return text
    cc = _converter()
    if not cc:
        return text
    return cc.convert(text)


def convert_segments(segments: List[dict]) -> List[dict]:
    """Convert text (and per-word text) of every segment in place-ish."""
    if not config.TRADITIONAL_CHINESE or not _converter():
        return segments
    for seg in segments:
        seg["text"] = to_traditional(seg.get("text", ""))
        for w in seg.get("words") or []:
            w["word"] = to_traditional(w.get("word", ""))
    return segments
