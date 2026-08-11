"""Transcription engines.

Two interchangeable engines return the same shape:

    {"language": "en", "segments": [
        {"start": 0.0, "end": 2.4, "text": "...",
         "words": [{"start":0.0,"end":0.3,"word":"..."}, ...]}, ...]}

- local  : faster-whisper (offline, private, free)
- cloud  : OpenAI transcription API (chunked to respect the 25 MB cap)
"""
from __future__ import annotations

import wave
from pathlib import Path
from typing import Optional

from . import config

# Cache the local model between meetings; loading large-v3 is expensive.
_local_model = None
_live_model = None


def _get_local_model():
    global _local_model
    if _local_model is None:
        from faster_whisper import WhisperModel

        _local_model = WhisperModel(
            config.LOCAL_WHISPER_MODEL,
            device=config.LOCAL_WHISPER_DEVICE,
            compute_type=config.LOCAL_WHISPER_COMPUTE,
        )
    return _local_model


def _lang_arg(language: str) -> Optional[str]:
    return None if language == "auto" else language


def _get_live_model():
    global _live_model
    if _live_model is None:
        from faster_whisper import WhisperModel

        _live_model = WhisperModel(
            config.LIVE_WHISPER_MODEL,
            device=config.LOCAL_WHISPER_DEVICE,
            compute_type=config.LIVE_WHISPER_COMPUTE,
        )
    return _live_model


def transcribe_window(samples, language: str = "auto", prompt: str = "") -> dict:
    """Fast, low-latency transcription of a short 16 kHz float32 window for live
    captions. Greedy (beam=1), no word timestamps — accuracy is refined by the
    full pass after recording stops."""
    model = _get_live_model()
    seg_iter, info = model.transcribe(
        samples, language=_lang_arg(language), initial_prompt=prompt or None,
        beam_size=1, vad_filter=False, word_timestamps=False,
        condition_on_previous_text=False,
    )
    text = "".join(s.text for s in seg_iter).strip()
    return {"text": text, "language": info.language or ""}


SR = 16000
_ALLOWED = ("en", "zh")  # this tool handles English + Mandarin only


def _collect(seg_iter, offset: float = 0.0) -> list:
    out = []
    for s in seg_iter:
        words = [
            {"start": float(w.start) + offset, "end": float(w.end) + offset, "word": w.word}
            for w in (s.words or [])
        ]
        out.append(
            {"start": float(s.start) + offset, "end": float(s.end) + offset,
             "text": s.text.strip(), "words": words}
        )
    return out


def _transcribe_whole(model, audio, lang, prompt: str) -> dict:
    seg_iter, info = model.transcribe(
        audio, language=lang, initial_prompt=prompt or None,
        word_timestamps=True, vad_filter=True, beam_size=config.LOCAL_WHISPER_BEAM,
    )
    return {"language": info.language or (lang or ""), "segments": _collect(seg_iter)}


def _group_chunks(speech, max_samples, gap_samples):
    """Merge VAD speech spans into chunks that break at silences / length caps,
    so a language switch between utterances lands on a chunk boundary."""
    chunks = []
    cs, ce = speech[0]["start"], speech[0]["end"]
    for sp in speech[1:]:
        if sp["start"] - ce <= gap_samples and sp["end"] - cs <= max_samples:
            ce = sp["end"]
        else:
            chunks.append((cs, ce)); cs, ce = sp["start"], sp["end"]
    chunks.append((cs, ce))
    return chunks


def transcribe_local(wav_path: Path, language: str, prompt: str) -> dict:
    from faster_whisper.audio import decode_audio
    from faster_whisper.vad import VadOptions, get_speech_timestamps

    model = _get_local_model()
    audio = decode_audio(str(wav_path), sampling_rate=SR)
    forced = _lang_arg(language)

    # A forced language needs no per-chunk detection.
    if forced is not None:
        return _transcribe_whole(model, audio, forced, prompt)

    # Auto: detect language per speech chunk so EN and 中文 utterances are each
    # transcribed correctly even when they alternate across the meeting.
    vad_opts = VadOptions(min_silence_duration_ms=300, speech_pad_ms=150, max_speech_duration_s=25)
    speech = get_speech_timestamps(audio, vad_options=vad_opts)
    if not speech:
        return _transcribe_whole(model, audio, None, prompt)

    # Keep VAD's utterance boundaries (it already split on >=300 ms silences);
    # only glue back spans separated by a breath (<=0.1 s). This way a language
    # switch between utterances is detected per utterance, not averaged away.
    chunks = _group_chunks(speech, max_samples=25 * SR, gap_samples=int(0.1 * SR))
    segments, langs = [], []
    common = dict(initial_prompt=prompt or None, word_timestamps=True,
                  vad_filter=False, beam_size=config.LOCAL_WHISPER_BEAM,
                  condition_on_previous_text=False)
    for cs, ce in chunks:
        clip = audio[cs:ce]
        seg_iter, info = model.transcribe(clip, language=None, **common)
        detected = info.language
        # Enforce the English/Mandarin-only constraint.
        if detected not in _ALLOWED:
            probs = dict(info.all_language_probs or [])
            detected = "en" if probs.get("en", 0) >= probs.get("zh", 0) else "zh"
            seg_iter, info = model.transcribe(clip, language=detected, **common)
        langs.append(detected)
        segments.extend(_collect(seg_iter, offset=cs / SR))

    segments.sort(key=lambda x: x["start"])
    return {"language": "+".join(sorted(set(langs))) if langs else "", "segments": segments}


def _slice_wav(src: Path, start_s: float, end_s: float, dst: Path) -> Path:
    with wave.open(str(src), "rb") as wf:
        rate = wf.getframerate()
        nch = wf.getnchannels()
        sw = wf.getsampwidth()
        wf.setpos(int(start_s * rate))
        frames = wf.readframes(int((end_s - start_s) * rate))
    with wave.open(str(dst), "wb") as out:
        out.setnchannels(nch)
        out.setsampwidth(sw)
        out.setframerate(rate)
        out.writeframes(frames)
    return dst


def transcribe_cloud(wav_path: Path, language: str, prompt: str) -> dict:
    from openai import OpenAI

    client = OpenAI(api_key=config.OPENAI_API_KEY)

    with wave.open(str(wav_path), "rb") as wf:
        duration = wf.getnframes() / float(wf.getframerate() or 16000)

    chunk = max(60, config.CLOUD_CHUNK_SECONDS)
    offsets = [i * chunk for i in range(int(duration // chunk) + 1)]
    all_segments = []
    detected = language if language != "auto" else ""

    for off in offsets:
        end = min(off + chunk, duration)
        if end - off < 0.1:
            continue
        part = wav_path.with_name(f"{wav_path.stem}.part{int(off)}.wav")
        _slice_wav(wav_path, off, end, part)
        try:
            with open(part, "rb") as f:
                kwargs = dict(
                    model=config.OPENAI_TRANSCRIBE_MODEL,
                    file=f,
                    response_format="verbose_json",
                    timestamp_granularities=["segment", "word"],
                )
                if language != "auto":
                    kwargs["language"] = language
                if prompt:
                    kwargs["prompt"] = prompt
                resp = client.audio.transcriptions.create(**kwargs)
        finally:
            part.unlink(missing_ok=True)

        detected = detected or getattr(resp, "language", "") or ""
        words = getattr(resp, "words", None) or []
        for seg in getattr(resp, "segments", None) or []:
            s0, s1 = float(seg.start) + off, float(seg.end) + off
            seg_words = [
                {"start": float(w.start) + off, "end": float(w.end) + off, "word": w.word}
                for w in words
                if float(w.start) + off >= s0 - 0.05 and float(w.end) + off <= s1 + 0.05
            ]
            all_segments.append(
                {"start": s0, "end": s1, "text": seg.text.strip(), "words": seg_words}
            )

    return {"language": detected, "segments": all_segments}


def transcribe(wav_path: Path, engine: str, language: str, prompt: str) -> dict:
    if engine == "cloud":
        return transcribe_cloud(wav_path, language, prompt)
    return transcribe_local(wav_path, language, prompt)
