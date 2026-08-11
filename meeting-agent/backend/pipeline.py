"""Orchestrates the full pipeline for one meeting and reports progress.

Steps: normalise audio -> transcribe -> (diarize + merge) -> summarize.
Runs on a single background worker thread so heavy models are serialized.
"""
from __future__ import annotations

import traceback
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from . import audio, config, diarize, storage, summarize, textconv, transcribe

_executor = ThreadPoolExecutor(max_workers=1)


def submit(meeting_id: str) -> None:
    _executor.submit(_run, meeting_id)


def _progress(mid: str, stage: str, pct: int) -> None:
    storage.update(mid, status="processing", stage=stage, progress=pct)


def _run(meeting_id: str) -> None:
    m = storage.get(meeting_id)
    if not m:
        return
    opts = m["options"]
    src = Path(m["audio_path"])
    wav = src.with_suffix(".16k.wav")
    try:
        _progress(meeting_id, "準備音訊中", 5)
        audio.to_wav_16k_mono(src, wav)
        duration = audio.wav_duration(wav)
        storage.update(meeting_id, duration=duration)

        _progress(meeting_id, "轉錄中", 20)
        tr = transcribe.transcribe(
            wav, engine=m["engine"], language=opts.get("language", "auto"),
            prompt=opts.get("vocabulary", ""),
        )
        segments = textconv.convert_segments(tr["segments"])
        language = tr["language"]

        diarized = False
        speakers: list[str] = []
        if opts.get("diarize") and diarize.available() and segments:
            _progress(meeting_id, "辨識發言者中", 60)
            turns = diarize.diarize(wav, opts.get("num_speakers"))
            segments = diarize.apply_speakers(segments, turns)
            speakers = sorted({s["speaker"] for s in segments if s.get("speaker")})
            diarized = True

        summary = None
        provider = config.resolve_summary_provider(opts.get("summary_provider", ""))
        if provider and segments:
            _progress(meeting_id, f"摘要與重點整理中（{provider}）", 85)
            summary = summarize.summarize(
                segments, opts.get("summary_language", "zh"), provider=provider
            )

        result = {
            "language": language,
            "duration": duration,
            "engine": m["engine"],
            "diarized": diarized,
            "speakers": speakers,
            "segments": segments,
            "summary": summary,
        }
        title = m["title"]
        if (not title or title == "未命名會議") and summary and summary.get("title"):
            title = summary["title"]
        storage.update(
            meeting_id, status="done", stage="完成", progress=100,
            result=result, title=title, error=None,
        )
    except Exception as exc:  # noqa: BLE001 - report any failure to the UI
        storage.update(
            meeting_id, status="error", stage="失敗", progress=100,
            error=f"{exc}\n{traceback.format_exc()[-1500:]}",
        )
    finally:
        try:
            wav.unlink(missing_ok=True)
        except OSError:
            pass
