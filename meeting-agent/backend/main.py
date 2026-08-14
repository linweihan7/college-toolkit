"""FastAPI app: REST API + serves the local web UI."""
from __future__ import annotations

import json
import time
from pathlib import Path

from typing import Optional

from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from . import clean, config, pipeline, storage, summarize, transcribe
from .schemas import ProcessOptions

FRONTEND = Path(__file__).resolve().parent.parent / "frontend"

app = FastAPI(title="Meeting Scribe")


SESSION_COOKIE = "ms_session"


def owner_dep(request: Request) -> Optional[str]:
    """Visitor identity. In public mode every browser gets its own random id and
    all queries are scoped to it, so one visitor can never see another's meetings
    (nor the host's). In private mode returns None = no scoping.

    Never falls back to a shared constant: an unidentified caller gets a value
    that matches no stored row, so it sees nothing rather than someone else's data.
    """
    if not config.PUBLIC_MODE:
        return None
    return request.cookies.get(SESSION_COOKIE) or "__unidentified__"


@app.middleware("http")
async def attach_session(request: Request, call_next):
    """Issue a per-visitor session id in public mode.

    The new id is written into the request scope's raw headers so that the
    Request object FastAPI builds for the endpoint/dependency parses it too —
    setting an attribute on this Request would not propagate, which would leave
    every first-time visitor sharing one bucket.
    """
    if not config.PUBLIC_MODE:
        return await call_next(request)

    sid = request.cookies.get(SESSION_COOKIE)
    new = not sid
    if new:
        sid = secrets_token()
        headers = [(k, v) for k, v in request.scope.get("headers", [])]
        cookie_pair = f"{SESSION_COOKIE}={sid}".encode()
        for i, (k, v) in enumerate(headers):
            if k.lower() == b"cookie":
                headers[i] = (k, v + b"; " + cookie_pair)
                break
        else:
            headers.append((b"cookie", cookie_pair))
        request.scope["headers"] = headers

    response = await call_next(request)
    if new:
        response.set_cookie(
            SESSION_COOKIE, sid, max_age=60 * 60 * 24 * 30,
            httponly=True, samesite="lax",
        )
    return response


def secrets_token() -> str:
    import secrets

    return secrets.token_urlsafe(24)


@app.middleware("http")
async def require_password(request: Request, call_next):
    """HTTP Basic auth, active whenever APP_PASSWORD is set. Essential before
    exposing a private instance past localhost — meetings are otherwise readable
    by anyone who reaches the URL. Public mode skips it by design: there, access
    control is per-visitor session isolation instead."""
    if config.PUBLIC_MODE:
        return await call_next(request)
    if not config.APP_PASSWORD:
        return await call_next(request)

    import base64
    import secrets

    header = request.headers.get("authorization", "")
    ok = False
    if header.startswith("Basic "):
        try:
            user, _, pw = base64.b64decode(header[6:]).decode("utf-8").partition(":")
            ok = secrets.compare_digest(user, config.APP_USER) and secrets.compare_digest(
                pw, config.APP_PASSWORD
            )
        except Exception:  # noqa: BLE001 - malformed header
            ok = False
    if not ok:
        return JSONResponse(
            {"detail": "需要登入"}, status_code=401,
            headers={"WWW-Authenticate": 'Basic realm="Meeting Scribe"'},
        )
    return await call_next(request)


@app.on_event("startup")
def _startup() -> None:
    storage.init()
    storage.reset_stale()
    try:
        storage.apply_retention(int(storage.get_setting("retention_days", "0") or 0))
    except Exception:  # noqa: BLE001
        pass


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
    """Live proofreading: LLM when a key is configured, else offline tidy."""
    prov = config.resolve_ai_provider(provider)      # "" -> offline rule-based
    rough = (payload.get("text") or "").strip()
    if not rough:
        return {"text": "", "provider": prov or "offline"}
    try:
        return {"text": clean.clean_text(rough, prov, payload.get("context", "")),
                "provider": prov or "offline"}
    except Exception as exc:  # noqa: BLE001 - never break the live stream; fall back to raw
        return {"text": rough, "provider": prov or "offline", "error": str(exc)}


@app.post("/api/meetings/{mid}/cleanup")
def cleanup_meeting(mid: str, provider: str = "", owner: Optional[str] = Depends(owner_dep)):
    """Proofread the whole stored transcript (line-by-line, alignment kept).
    Uses an LLM when a key is configured, otherwise the offline rule-based tidy."""
    prov = config.resolve_ai_provider(provider)      # "" -> offline rule-based
    m = storage.get(mid, owner=owner)
    if not m or not (m.get("result") or {}).get("segments"):
        raise HTTPException(400, "No transcript to clean")
    result = m["result"]
    segs = result["segments"]
    try:
        cleaned = clean.clean_lines([s["text"] for s in segs], prov)
    except Exception as exc:  # noqa: BLE001 - fall back to the offline tidy
        cleaned = clean.tidy_lines([s["text"] for s in segs])
        prov = ""
    for s, c in zip(segs, cleaned):
        s["clean"] = c            # keep the raw text; store the cleaned one alongside
    result["cleaned_by"] = prov or "offline"
    storage.update(mid, result=result)
    return {"ok": True, "provider": prov or "offline"}


@app.post("/api/meetings")
async def create_meeting(audio: UploadFile = File(...), options: str = Form("{}"), owner: Optional[str] = Depends(owner_dep)):
    try:
        opts = ProcessOptions(**json.loads(options or "{}"))
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(400, f"Invalid options: {exc}")

    caps = config.capabilities()
    if not caps["engines"][opts.engine]["available"]:
        raise HTTPException(
            400, f"Engine '{opts.engine}' unavailable: {caps['engines'][opts.engine]['reason']}"
        )

    # Public mode: rate-limit per visitor — transcription burns the host's CPU.
    if config.PUBLIC_MODE and owner:
        recent = storage.count_recent(owner)
        if recent >= config.PUBLIC_MAX_PER_HOUR:
            raise HTTPException(
                429, f"每小時最多 {config.PUBLIC_MAX_PER_HOUR} 場會議，請稍後再試。"
            )

    data = await audio.read()
    if config.PUBLIC_MODE and len(data) > config.PUBLIC_MAX_UPLOAD_MB * 1024 * 1024:
        raise HTTPException(
            413, f"檔案過大：公開版每個檔案上限 {config.PUBLIC_MAX_UPLOAD_MB} MB。"
        )

    suffix = Path(audio.filename or "recording.webm").suffix or ".webm"
    dest = config.AUDIO_DIR / f"{int(time.time() * 1000)}{suffix}"
    with open(dest, "wb") as f:
        f.write(data)

    mid = storage.create_meeting(opts.title, opts.engine, opts.model_dump(), dest, owner=owner or "")
    pipeline.submit(mid)
    return {"id": mid}


@app.get("/api/meetings")
def list_meetings(owner: Optional[str] = Depends(owner_dep)):
    return storage.list_meetings(owner=owner)


@app.get("/api/meetings/{mid}")
def get_meeting(mid: str, owner: Optional[str] = Depends(owner_dep)):
    m = storage.get(mid, owner=owner)
    if not m:
        raise HTTPException(404, "Not found")
    return m


@app.get("/api/meetings/{mid}/status")
def meeting_status(mid: str, owner: Optional[str] = Depends(owner_dep)):
    m = storage.get(mid, include_result=False, owner=owner)
    if not m:
        raise HTTPException(404, "Not found")
    return {k: m[k] for k in ("id", "status", "stage", "progress", "error", "title", "duration")}


@app.get("/api/meetings/{mid}/audio")
def meeting_audio(mid: str, owner: Optional[str] = Depends(owner_dep)):
    m = storage.get(mid, include_result=False, owner=owner)
    if not m:
        raise HTTPException(404, "Not found")
    p = Path(m["audio_path"])
    if not p.exists():
        raise HTTPException(404, "Audio missing")
    return FileResponse(p)


@app.post("/api/meetings/{mid}/resummarize")
def resummarize(mid: str, provider: str = "", owner: Optional[str] = Depends(owner_dep)):
    """(Re)generate the summary for an already-transcribed meeting — e.g. after
    adding an API key, or to switch/compare AI providers."""
    m = storage.get(mid, owner=owner)
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


@app.get("/api/settings")
def get_settings():
    return {
        "confidential_mode": storage.get_setting("confidential_mode", "0") == "1",
        "retention_days": int(storage.get_setting("retention_days", "0") or 0),
        "audio_enhance": storage.get_setting("audio_enhance", "1") == "1",
    }


@app.put("/api/settings")
def put_settings(payload: dict):
    if config.PUBLIC_MODE:
        raise HTTPException(403, "公開版無法變更伺服器設定")
    if "confidential_mode" in payload:
        storage.set_setting("confidential_mode", "1" if payload["confidential_mode"] else "0")
    if "retention_days" in payload:
        storage.set_setting("retention_days", str(int(payload.get("retention_days") or 0)))
    if "audio_enhance" in payload:
        storage.set_setting("audio_enhance", "1" if payload["audio_enhance"] else "0")
    return {"ok": True}


@app.get("/api/meetings/{mid}/minutes.docx")
def minutes_docx(mid: str, owner: Optional[str] = Depends(owner_dep)):
    m = storage.get(mid, owner=owner)
    if not m or not m.get("result"):
        raise HTTPException(404, "Not found")
    from . import export_docx

    out = config.DATA_DIR / f"{mid}.docx"
    export_docx.build_docx(m, out)
    safe = "".join(ch for ch in (m.get("title") or "meeting") if ch.isalnum() or ch in " 一-鿿").strip() or "meeting"
    return FileResponse(
        out, filename=f"{safe}.docx",
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    )


@app.get("/api/search")
def search_meetings(q: str = "", owner: Optional[str] = Depends(owner_dep)):
    """Full-text search across every meeting's transcript."""
    q = q.strip().lower()
    if not q:
        return {"results": []}
    results = []
    for meta in storage.list_meetings(owner=owner):
        if meta["status"] != "done":
            continue
        full = storage.get(meta["id"], owner=owner)
        names = (full.get("result") or {}).get("speaker_names", {})
        for s in (full.get("result") or {}).get("segments", []):
            text = s.get("edited") or s.get("clean") or s.get("text", "")
            if q in text.lower():
                spk = names.get(s.get("speaker"), s.get("speaker"))
                results.append({"id": meta["id"], "title": meta["title"],
                                "start": s["start"], "speaker": spk, "text": text})
                if len(results) >= 100:
                    return {"results": results}
    return {"results": results}


@app.get("/api/glossary")
def get_glossary():
    return {"terms": storage.get_setting("glossary", "")}


@app.put("/api/glossary")
def put_glossary(payload: dict):
    if config.PUBLIC_MODE:
        raise HTTPException(403, "公開版無法儲存共用詞彙")
    storage.set_setting("glossary", (payload.get("terms") or "").strip())
    return {"ok": True}


@app.post("/api/meetings/{mid}/speakers")
def set_speaker_names(mid: str, payload: dict, owner: Optional[str] = Depends(owner_dep)):
    """Map raw diarization labels to real names, e.g. {"Speaker 1": "王經理"}."""
    m = storage.get(mid, owner=owner)
    if not m or not m.get("result"):
        raise HTTPException(404, "Not found")
    result = m["result"]
    result["speaker_names"] = {k: v.strip() for k, v in (payload.get("names") or {}).items() if v.strip()}
    storage.update(mid, result=result)
    return {"ok": True, "speaker_names": result["speaker_names"]}


@app.post("/api/meetings/{mid}/segment")
def edit_segment(mid: str, payload: dict, owner: Optional[str] = Depends(owner_dep)):
    """Manually correct one transcript line (stored as an override)."""
    m = storage.get(mid, owner=owner)
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
def retranscribe(mid: str, language: str = "", diarize: str = "", num_speakers: int = -1, owner: Optional[str] = Depends(owner_dep)):
    """Re-run the full pipeline on the already-saved audio, optionally changing
    language / diarization — e.g. to redo an auto-detected meeting as zh only."""
    import json as _json

    m = storage.get(mid, owner=owner)
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
def compare(mid: str, providers: str = "", owner: Optional[str] = Depends(owner_dep)):
    """Summarize the same transcript with several AIs so they can be compared
    side by side. `providers` is a comma list; empty = all available."""
    m = storage.get(mid, owner=owner)
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
def delete_meeting(mid: str, owner: Optional[str] = Depends(owner_dep)):
    if not storage.delete(mid, owner=owner):
        raise HTTPException(404, "Not found")
    return {"ok": True}


# --- Static UI ---------------------------------------------------------------
@app.get("/")
def index():
    return FileResponse(FRONTEND / "index.html")


app.mount("/", StaticFiles(directory=FRONTEND), name="static")
