"""Speaker diarization + merging speakers into the transcript.

Two backends, auto-selected:
- "pyannote": highest accuracy, needs pyannote.audio + a HuggingFace token.
- "offline" : no token — voice embeddings (resemblyzer) per utterance, then
  clustering (scikit-learn). Works out of the box once those two are installed.

If neither is available the pipeline skips diarization and returns an
un-labelled transcript.
"""
from __future__ import annotations

import wave
from pathlib import Path
from typing import List, Optional

from . import config

_pipeline = None
_encoder = None


def backend() -> Optional[str]:
    from .config import _has_module

    if _has_module("pyannote.audio") and config.HUGGINGFACE_TOKEN:
        return "pyannote"
    if _has_module("resemblyzer") and _has_module("sklearn"):
        return "offline"
    return None


def available() -> bool:
    return backend() is not None


def diarize(wav_path: Path, num_speakers: Optional[int] = None, segments: Optional[List[dict]] = None) -> List[dict]:
    """Return [{start, end, speaker}] turns (raw labels; relabelled later)."""
    b = backend()
    if b == "pyannote":
        return _diarize_pyannote(wav_path, num_speakers)
    if b == "offline":
        return _diarize_offline(wav_path, segments or [], num_speakers)
    return []


# --- pyannote backend --------------------------------------------------------
def _diarize_pyannote(wav_path: Path, num_speakers: Optional[int]) -> List[dict]:
    global _pipeline
    if _pipeline is None:
        from pyannote.audio import Pipeline

        _pipeline = Pipeline.from_pretrained(
            config.DIARIZATION_MODEL, use_auth_token=config.HUGGINGFACE_TOKEN
        )
    kwargs = {"num_speakers": int(num_speakers)} if num_speakers else {}
    annotation = _pipeline(str(wav_path), **kwargs)
    turns = [
        {"start": float(seg.start), "end": float(seg.end), "speaker": speaker}
        for seg, _, speaker in annotation.itertracks(yield_label=True)
    ]
    turns.sort(key=lambda t: t["start"])
    return turns


# --- offline backend (no token) ---------------------------------------------
def _load_wav_f32(wav_path: Path):
    import numpy as np

    with wave.open(str(wav_path), "rb") as wf:
        sr = wf.getframerate()
        raw = wf.readframes(wf.getnframes())
    data = np.frombuffer(raw, dtype="int16").astype("float32") / 32768.0
    return data, sr


def _cluster(embeddings, num_speakers: Optional[int]):
    from sklearn.cluster import AgglomerativeClustering

    n = len(embeddings)
    if n <= 1:
        return [0] * n
    if num_speakers and num_speakers >= 1:
        k = min(int(num_speakers), n)
        model = AgglomerativeClustering(n_clusters=k, metric="cosine", linkage="average")
    else:
        # Auto: split when voices are sufficiently different (cosine distance).
        # Real speech has high within-speaker variance, so a low threshold badly
        # over-splits (one person -> many "speakers"). 0.42 is far more stable.
        # Auto speaker-counting is inherently unreliable — set the expected
        # speaker count in the UI whenever you know it.
        model = AgglomerativeClustering(
            n_clusters=None, distance_threshold=0.42, metric="cosine", linkage="average"
        )
    return list(model.fit_predict(embeddings))


def _diarize_offline(wav_path: Path, segments: List[dict], num_speakers: Optional[int]) -> List[dict]:
    if not segments:
        return []
    import numpy as np
    from resemblyzer import VoiceEncoder

    global _encoder
    if _encoder is None:
        _encoder = VoiceEncoder(verbose=False)

    wav, sr = _load_wav_f32(wav_path)
    valid_idx, embs = [], []
    for i, seg in enumerate(segments):
        a, b = int(seg["start"] * sr), int(seg["end"] * sr)
        clip = wav[a:b]
        if len(clip) < int(0.4 * sr):  # too short to embed reliably
            continue
        try:
            embs.append(_encoder.embed_utterance(clip))
            valid_idx.append(i)
        except Exception:
            continue
    if not embs:
        return []

    labels = _cluster(np.array(embs), num_speakers)
    turns = []
    for i, lab in zip(valid_idx, labels):
        turns.append(
            {"start": segments[i]["start"], "end": segments[i]["end"], "speaker": f"SPEAKER_{int(lab):02d}"}
        )
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
