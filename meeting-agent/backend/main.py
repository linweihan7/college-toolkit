"""FastAPI app: REST API + serves the local web UI."""
from __future__ import annotations

import json
import time
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from . import clean, config, pipeline, storage, summarize, transcribe
from .schemas import ProcessOptions

FRONTEND = Path(__file__).resolve().parent.parent / "frontend"

app = FastAPI(title="Meeting Scribe")


@app.on_event("startup")
def _startup() -> None:
    storage.init()
    storage.reset_stale()


@app.get("/api/config")
def get_config():
    return config.capabilities()


@app.post("/api/transcribe_chunk")
async def transcribe_chunk(request: Request, sample_rate: int = 16000, language: str = "auto"):
    """Live captions: transcribe one short raw-PCM (int16 mono) window."""
    if not config.capabilities()["live"]["available"]:
        raise HTTPException(400, "Live captions need the local engine (faster-whisper)")
    import numpy as np

    raw = await request.body()
    if len(raw) < 2:
        return {"text": ""}
    pcm = np.frombuffer(raw, dtype="<i2").astype("float32") / 32768.0
    if sample_rate != 16000:
        import librosa

        pcm = librosa.resample(pcm, orig_sr=sample_rate, target_sr=16000)
    lang = language if language in ("en", "zh") else "auto"
    try:
        return transcribe.transcribe_window(pcm, lang)
    except Exception as exc:  # noqa: BLE001 - never break the live stream
        return {"text": "", "error": str(exc)}


@app.post("/api/clean")
async def clean_live(payload: dict, provider: str = ""):
    """Live AI proofreading: polish a short passage of rough captions."""
    prov = config.resolve_ai_provider(provider)
    if not prov:
        raise HTTPException(400, "AI 校對需要 Claude / GPT / Gemini 金鑰（Gemini 有免費額度）")
    rough = (payload.get("text") or "").strip()
    if not rough:
        return {"text": "", "provider": prov}
    try:
        return {"text": clean.clean_text(rough, prov, payload.get("context", "")), "provider": prov}
    except Exception as exc:  # noqa: BLE001 - never break the live stream; fall back to raw
        return {"text": rough, "provider": prov, "error": str(exc)}


@app.post("/api/meetings/{mid}/cleanup")
def cleanup_meeting(mid: str, provider: str = ""):
    """AI-proofread the whole stored transcript (line-by-line, alignment kept)."""
    prov = config.resolve_ai_provider(provider)
    if not prov:
        raise HTTPException(400, "AI 校對需要 Claude / GPT / Gemini 金鑰")
    m = storage.get(mid)
    if not m or not (m.get("result") or {}).get("segments"):
        raise HTTPException(400, "No transcript to clean")
    result = m["result"]
    segs = result["segments"]
    try:
        cleaned = clean.clean_lines([s["text"] for s in segs], prov)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(502, f"{prov} cleanup failed: {exc}")
    for s, c in zip(segs, cleaned):
        s["clean"] = c            # keep the raw text; store the AI version alongside
    result["cleaned_by"] = prov
    storage.update(mid, result=result)
    return {"ok": True, "provider": prov}


@app.post("/api/meetings")
async def create_meeting(audio: UploadFile = File(...), options: str = Form("{}")):
    try:
        opts = ProcessOptions(**json.loads(options or "{}"))
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(400, f"Invalid options: {exc}")

    caps = config.capabilities()
    if not caps["engines"][opts.engine]["available"]:
        raise HTTPException(
            400, f"Engine '{opts.engine}' unavailable: {caps['engines'][opts.engine]['reason']}"
        )

    suffix = Path(audio.filename or "recording.webm").suffix or ".webm"
    dest = config.AUDIO_DIR / f"{int(time.time() * 1000)}{suffix}"
    with open(dest, "wb") as f:
        f.write(await audio.read())

    mid = storage.create_meeting(opts.title, opts.engine, opts.model_dump(), dest)
    pipeline.submit(mid)
    return {"id": mid}


@app.get("/api/meetings")
def list_meetings():
    return storage.list_meetings()


@app.get("/api/meetings/{mid}")
def get_meeting(mid: str):
    m = storage.get(mid)
    if not m:
        raise HTTPException(404, "Not found")
    return m


@app.get("/api/meetings/{mid}/status")
def meeting_status(mid: str):
    m = storage.get(mid, include_result=False)
    if not m:
        raise HTTPException(404, "Not found")
    return {k: m[k] for k in ("id", "status", "stage", "progress", "error", "title", "duration")}


@app.get("/api/meetings/{mid}/audio")
def meeting_audio(mid: str):
    m = storage.get(mid, include_result=False)
    if not m:
        raise HTTPException(404, "Not found")
    p = Path(m["audio_path"])
    if not p.exists():
        raise HTTPException(404, "Audio missing")
    return FileResponse(p)


@app.post("/api/meetings/{mid}/resummarize")
def resummarize(mid: str, provider: str = ""):
    """(Re)generate the summary for an already-transcribed meeting — e.g. after
    adding an API key, or to switch/compare AI providers."""
    m = storage.get(mid)
    if not m:
        raise HTTPException(404, "Not found")
    result = m.get("result")
    if not result or not result.get("segments"):
        raise HTTPException(400, "No transcript available to summarize")
    prov = config.resolve_summary_provider(provider)
    if not prov:
        raise HTTPException(400, "No summarization AI available — add a Claude/GPT/Gemini key to .env")
    try:
        summary = summarize.summarize(
            result["segments"], m["options"].get("summary_language", "zh"),
            provider=prov, names=result.get("speaker_names"),
        )
    except Exception as exc:  # noqa: BLE001 - surface provider/auth errors to the UI
        raise HTTPException(502, f"{prov} summarization failed: {exc}")

    result["summary"] = summary
    title = m["title"]
    if (not title or title == "未命名會議") and summary.get("title"):
        title = summary["title"]
    storage.update(mid, result=result, title=title)
    return {"summary": summary, "provider": prov}


@app.get("/api/glossary")
def get_glossary():
    return {"terms": storage.get_setting("glossary", "")}


@app.put("/api/glossary")
def put_glossary(payload: dict):
    storage.set_setting("glossary", (payload.get("terms") or "").strip())
    return {"ok": True}


@app.post("/api/meetings/{mid}/speakers")
def set_speaker_names(mid: str, payload: dict):
    """Map raw diarization labels to real names, e.g. {"Speaker 1": "王經理"}."""
    m = storage.get(mid)
    if not m or not m.get("result"):
        raise HTTPException(404, "Not found")
    result = m["result"]
    result["speaker_names"] = {k: v.strip() for k, v in (payload.get("names") or {}).items() if v.strip()}
    storage.update(mid, result=result)
    return {"ok": True, "speaker_names": result["speaker_names"]}


@app.post("/api/meetings/{mid}/segment")
def edit_segment(mid: str, payload: dict):
    """Manually correct one transcript line (stored as an override)."""
    m = storage.get(mid)
    if not m or not m.get("result"):
        raise HTTPException(404, "Not found")
    result = m["result"]
    segs = result.get("segments") or []
    idx = int(payload.get("index", -1))
    if not (0 <= idx < len(segs)):
        raise HTTPException(400, "Bad segment index")
    segs[idx]["edited"] = (payload.get("text") or "").strip()
    storage.update(mid, result=result)
    return {"ok": True}


@app.post("/api/meetings/{mid}/retranscribe")
def retranscribe(mid: str, language: str = "", diarize: str = "", num_speakers: int = -1):
    """Re-run the full pipeline on the already-saved audio, optionally changing
    language / diarization — e.g. to redo an auto-detected meeting as zh only."""
    import json as _json

    m = storage.get(mid)
    if not m:
        raise HTTPException(404, "Not found")
    if not Path(m["audio_path"]).exists():
        raise HTTPException(400, "Audio file no longer available")
    opts = m["options"]
    if language:
        opts["language"] = language
    if diarize in ("true", "false"):
        opts["diarize"] = diarize == "true"
    if num_speakers >= 0:
        opts["num_speakers"] = num_speakers or None
    storage.update(
        mid, options_json=_json.dumps(opts), status="queued", stage="排隊中",
        progress=0, error=None, result=None,
    )
    pipeline.submit(mid)
    return {"id": mid}


@app.post("/api/meetings/{mid}/compare")
def compare(mid: str, providers: str = ""):
    """Summarize the same transcript with several AIs so they can be compared
    side by side. `providers` is a comma list; empty = all available."""
    m = storage.get(mid)
    if not m:
        raise HTTPException(404, "Not found")
    result = m.get("result")
    if not result or not result.get("segments"):
        raise HTTPException(400, "No transcript available to summarize")

    caps = config.capabilities()["summarization"]["providers"]
    want = [p.strip() for p in providers.split(",") if p.strip()] if providers else list(caps)
    want = [p for p in want if caps.get(p, {}).get("available")]
    if not want:
        raise HTTPException(400, "No summarization AI available")

    lang = m["options"].get("summary_language", "zh")
    out, errors = {}, {}
    for p in want:
        try:
            out[p] = summarize.summarize(result["segments"], lang, provider=p, names=result.get("speaker_names"))
        except Exception as exc:  # noqa: BLE001 - report per-provider failures
            errors[p] = str(exc)
    result["comparisons"] = out
    storage.update(mid, result=result)
    return {"results": out, "errors": errors}


@app.delete("/api/meetings/{mid}")
def delete_meeting(mid: str):
    if not storage.delete(mid):
        raise HTTPException(404, "Not found")
    return {"ok": True}


# --- Static UI ---------------------------------------------------------------
@app.get("/")
def index():
    return FileResponse(FRONTEND / "index.html")


app.mount("/", StaticFiles(directory=FRONTEND), name="static")
