"""SQLite-backed persistence for meetings.

Audio lives on disk under data/audio/; transcript + summary are stored as a
JSON blob in the row so a meeting is fully self-contained.
"""
from __future__ import annotations

import json
import sqlite3
import time
import uuid
from pathlib import Path
from typing import List, Optional

from . import config

_SCHEMA = """
CREATE TABLE IF NOT EXISTS meetings (
    id           TEXT PRIMARY KEY,
    title        TEXT,
    created_at   REAL,
    status       TEXT,        -- queued | processing | done | error
    stage        TEXT,        -- human-readable current step
    progress     INTEGER,     -- 0..100
    engine       TEXT,
    options_json TEXT,
    audio_path   TEXT,
    duration     REAL,
    result_json  TEXT,
    error        TEXT
);
CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT);
"""


def get_setting(key: str, default: str = "") -> str:
    with _conn() as c:
        row = c.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
    return row["value"] if row else default


def set_setting(key: str, value: str) -> None:
    with _conn() as c:
        c.execute(
            "INSERT INTO settings(key,value) VALUES(?,?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, value),
        )


def _conn() -> sqlite3.Connection:
    conn = sqlite3.connect(config.DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def init() -> None:
    with _conn() as c:
        c.executescript(_SCHEMA)
        # Migration: per-visitor ownership for public multi-user mode.
        cols = {r["name"] for r in c.execute("PRAGMA table_info(meetings)")}
        if "owner" not in cols:
            c.execute("ALTER TABLE meetings ADD COLUMN owner TEXT DEFAULT ''")
            c.execute("CREATE INDEX IF NOT EXISTS idx_meetings_owner ON meetings(owner)")


def reset_stale() -> None:
    """Mark meetings left mid-processing (e.g. by a server restart) as errored,
    so they don't sit in 'processing' forever."""
    with _conn() as c:
        c.execute(
            "UPDATE meetings SET status='error', stage='已中斷', "
            "error='處理在完成前被中斷（例如伺服器重啟）。請刪除後重新匯入。' "
            "WHERE status IN ('processing','queued')"
        )


def create_meeting(title: str, engine: str, options: dict, audio_path: Path, owner: str = "") -> str:
    mid = uuid.uuid4().hex[:12]
    with _conn() as c:
        c.execute(
            "INSERT INTO meetings (id,title,created_at,status,stage,progress,engine,"
            "options_json,audio_path,duration,result_json,error,owner) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                mid, title or "未命名會議", time.time(), "queued", "排隊中", 0,
                engine, json.dumps(options), str(audio_path), 0.0, None, None, owner,
            ),
        )
    return mid


def count_recent(owner: str, seconds: int = 3600) -> int:
    """How many meetings this visitor started recently (rate limiting)."""
    with _conn() as c:
        row = c.execute(
            "SELECT COUNT(*) AS n FROM meetings WHERE owner=? AND created_at > ?",
            (owner, time.time() - seconds),
        ).fetchone()
    return int(row["n"]) if row else 0


def update(mid: str, **fields) -> None:
    if not fields:
        return
    if "result" in fields:
        fields["result_json"] = json.dumps(fields.pop("result"))
    cols = ", ".join(f"{k}=?" for k in fields)
    with _conn() as c:
        c.execute(f"UPDATE meetings SET {cols} WHERE id=?", (*fields.values(), mid))


def _row_to_dict(row: sqlite3.Row, include_result: bool = True) -> dict:
    d = dict(row)
    d["options"] = json.loads(d.pop("options_json") or "{}")
    result = d.pop("result_json")
    if include_result:
        d["result"] = json.loads(result) if result else None
    return d


def get(mid: str, include_result: bool = True, owner: Optional[str] = None) -> Optional[dict]:
    """owner=None means no scoping (private single-user mode). In public mode the
    caller passes the visitor's id so one visitor can never read another's."""
    with _conn() as c:
        if owner is None:
            row = c.execute("SELECT * FROM meetings WHERE id=?", (mid,)).fetchone()
        else:
            row = c.execute("SELECT * FROM meetings WHERE id=? AND owner=?", (mid, owner)).fetchone()
    return _row_to_dict(row, include_result) if row else None


def list_meetings(owner: Optional[str] = None) -> List[dict]:
    cols = ("SELECT id,title,created_at,status,stage,progress,engine,duration,error,options_json "
            "FROM meetings")
    with _conn() as c:
        if owner is None:
            rows = c.execute(cols + " ORDER BY created_at DESC").fetchall()
        else:
            rows = c.execute(cols + " WHERE owner=? ORDER BY created_at DESC", (owner,)).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        d["series"] = (json.loads(d.pop("options_json") or "{}")).get("series", "")
        out.append(d)
    return out


def apply_retention(days: int) -> int:
    """Delete meetings older than `days` (0 = keep forever)."""
    if not days or days <= 0:
        return 0
    cutoff = time.time() - days * 86400
    old = [r["id"] for r in list_meetings() if r["created_at"] < cutoff]
    for mid in old:
        delete(mid)
    return len(old)


def delete(mid: str, owner: Optional[str] = None) -> bool:
    row = get(mid, owner=owner)
    if not row:
        return False
    try:
        p = Path(row["audio_path"])
        if p.exists():
            p.unlink()
    except OSError:
        pass
    with _conn() as c:
        c.execute("DELETE FROM meetings WHERE id=?", (mid,))
    return True
