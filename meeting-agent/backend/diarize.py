"""Speaker diarization via pyannote, plus merging speakers into the transcript.

Diarization is optional: if pyannote or the HF token is missing, the pipeline
skips it and returns an un-labelled transcript.
"""
from __future__ import annotations

from pathlib import Path
from typing import List, Optional

from . import config

_pipeline = None


def available() -> bool:
    from .config import _has_module

    return _has_module("pyannote.audio") and bool(config.HUGGINGFACE_TOKEN)


def _get_pipeline():
    global _pipeline
    if _pipeline is None:
        from pyannote.audio import Pipeline

        _pipeline = Pipeline.from_pretrained(
            config.DIARIZATION_MODEL, use_auth_token=config.HUGGINGFACE_TOKEN
        )
    return _pipeline


def diarize(wav_path: Path, num_speakers: Optional[int] = None) -> List[dict]:
    """Return [{start, end, speaker}] turns."""
    pipeline = _get_pipeline()
    kwargs = {}
    if num_speakers:
        kwargs["num_speakers"] = int(num_speakers)
    annotation = pipeline(str(wav_path), **kwargs)

    turns = [
        {"start": float(seg.start), "end": float(seg.end), "speaker": speaker}
        for seg, _, speaker in annotation.itertracks(yield_label=True)
    ]
    turns.sort(key=lambda t: t["start"])
    return turns


def _label_at(turns: List[dict], start: float, end: float) -> Optional[str]:
    """Speaker whose turn overlaps [start,end] the most."""
    best, best_overlap = None, 0.0
    mid = (start + end) / 2
    for t in turns:
        overlap = min(end, t["end"]) - max(start, t["start"])
        if overlap > best_overlap:
            best, best_overlap = t["speaker"], overlap
    if best is None:  # fall back to whichever turn contains the midpoint
        for t in turns:
            if t["start"] <= mid <= t["end"]:
                return t["speaker"]
    return best


def apply_speakers(segments: List[dict], turns: List[dict]) -> List[dict]:
    """Attach speaker labels and re-map raw pyannote labels to Speaker 1..N.

    Words are labelled individually so a segment spanning two speakers can be
    split at the boundary — important for clean minutes.
    """
    order: List[str] = []

    def norm(raw: Optional[str]) -> Optional[str]:
        if raw is None:
            return None
        if raw not in order:
            order.append(raw)
        return f"Speaker {order.index(raw) + 1}"

    out: List[dict] = []
    for seg in segments:
        words = seg.get("words") or []
        if not words:
            seg = {**seg, "speaker": norm(_label_at(turns, seg["start"], seg["end"]))}
            out.append(seg)
            continue

        cur_label, cur_words = None, []
        for w in words:
            lbl = _label_at(turns, w["start"], w["end"])
            if cur_words and lbl != cur_label:
                out.append(_pack(cur_words, norm(cur_label)))
                cur_words = []
            cur_label, cur_words = lbl, cur_words + [w]
        if cur_words:
            out.append(_pack(cur_words, norm(cur_label)))
    return out


def _pack(words: List[dict], speaker: Optional[str]) -> dict:
    return {
        "start": words[0]["start"],
        "end": words[-1]["end"],
        "text": "".join(w["word"] for w in words).strip(),
        "speaker": speaker,
        "words": words,
    }
