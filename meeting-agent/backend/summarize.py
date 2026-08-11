"""Meeting summarization with a choice of AI provider.

Providers (Claude / OpenAI GPT / Google Gemini) share one prompt and return the
same JSON shape, so highlights, decisions, action items, topics and minutes are
identical in structure regardless of which model produced them.
"""
from __future__ import annotations

import json
import math
import re
from collections import Counter
from typing import Callable, List

from . import config

SYSTEM = """You are an expert executive assistant who writes precise, professional \
meeting minutes. The meeting audio was in Mandarin Chinese and/or English. \
Work only from the transcript provided — never invent decisions, owners, numbers \
or commitments that are not supported by the text. If the transcript is unclear, \
say so rather than guessing. Keep proper nouns, product names and figures exactly \
as spoken."""

INSTRUCTIONS = """From the transcript below, produce a JSON object with EXACTLY these keys:

- "title": a concise, specific meeting title (<= 10 words).
- "summary": 3-6 sentence executive summary of what happened and why it matters.
- "highlights": array of the most important points (5-10 short strings).
- "decisions": array of decisions that were actually made (strings). [] if none.
- "action_items": array of objects {"task","owner","due"}. Use the speaker label
  or named person as "owner" when attributable, else "". "due" is "" if unstated.
- "topics": array of {"title","summary"} covering each major discussion topic in order.
- "minutes_markdown": a clean, well-structured Markdown minutes document with
  sections (Summary, Attendees/Speakers if known, Key Points, Decisions,
  Action Items as a table, and a topic-by-topic breakdown).

Language rule: %(lang_rule)s

Return ONLY the JSON object. No prose, no code fences."""

LANG_RULES = {
    "auto": "Write in the dominant language of the meeting; if it is heavily mixed, write in English but keep Chinese terms where clearer.",
    "en": "Write everything in English.",
    "zh": "Write everything in Traditional Chinese (繁體中文). Do NOT use Simplified Chinese. Keep English proper nouns/acronyms in English.",
}


def _fmt(sec: float) -> str:
    m, s = divmod(int(sec), 60)
    h, m = divmod(m, 60)
    return f"{h:02d}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"


def _transcript_text(segments: List[dict]) -> str:
    lines = []
    for s in segments:
        spk = s.get("speaker")
        prefix = f"[{_fmt(s['start'])}] {spk}: " if spk else f"[{_fmt(s['start'])}] "
        lines.append(prefix + s["text"])
    return "\n".join(lines)


def _build_prompt(segments: List[dict], summary_language: str) -> str:
    return (
        INSTRUCTIONS % {"lang_rule": LANG_RULES.get(summary_language, LANG_RULES["auto"])}
        + "\n\n=== TRANSCRIPT ===\n"
        + _transcript_text(segments)
    )


# --- Providers ---------------------------------------------------------------
def _via_claude(prompt: str) -> str:
    from anthropic import Anthropic

    # With an explicit key use it; otherwise let the SDK read ANTHROPIC_AUTH_TOKEN
    # / ANTHROPIC_BASE_URL from the environment.
    client = Anthropic(api_key=config.ANTHROPIC_API_KEY) if config.ANTHROPIC_API_KEY else Anthropic()
    msg = client.messages.create(
        model=config.CLAUDE_MODEL,
        max_tokens=8000,
        system=SYSTEM,
        messages=[{"role": "user", "content": prompt}],
    )
    return "".join(b.text for b in msg.content if getattr(b, "type", "") == "text").strip()


def _via_openai(prompt: str) -> str:
    from openai import OpenAI

    client = OpenAI(api_key=config.OPENAI_API_KEY)
    resp = client.chat.completions.create(
        model=config.OPENAI_SUMMARY_MODEL,
        messages=[
            {"role": "system", "content": SYSTEM},
            {"role": "user", "content": prompt},
        ],
        response_format={"type": "json_object"},
    )
    return (resp.choices[0].message.content or "").strip()


def _via_gemini(prompt: str) -> str:
    from google import genai
    from google.genai import types

    client = genai.Client(api_key=config.GEMINI_API_KEY)
    resp = client.models.generate_content(
        model=config.GEMINI_MODEL,
        contents=prompt,
        config=types.GenerateContentConfig(
            system_instruction=SYSTEM,
            response_mime_type="application/json",
        ),
    )
    return (resp.text or "").strip()


PROVIDERS: dict[str, Callable[[str], str]] = {
    "claude": _via_claude,
    "openai": _via_openai,
    "gemini": _via_gemini,
}


# --- Offline extractive summarizer (no API key) ------------------------------
_STOP = set("the a an and or of to in on for with is are was were be this that it as at by we you they i our your".split())
_ACTION_EN = re.compile(r"\b(will|need to|needs to|must|schedule|follow[- ]?up|update|prepare|send|by friday|by monday|next monday|next week|due|deadline|assign)\b", re.I)
_ACTION_ZH = re.compile(r"(需要|之前|上線|準備|寄給|發送|更新|下週|下星期|週五|截止|負責|安排|跟進|準備一份|報告)")
_DECISION = re.compile(r"(decide|decided|agree|agreed|approved|confirm|final|決定|同意|通過|確認|拍板)", re.I)


def _sentences(segments: List[dict]) -> List[dict]:
    out = []
    for seg in segments:
        for part in re.split(r"(?<=[。！？!?\.])\s*", seg.get("text", "")):
            part = part.strip()
            if len(part) >= 2:
                out.append({"text": part, "speaker": seg.get("speaker"), "start": seg["start"]})
    return out


def _tokens(text: str) -> List[str]:
    en = re.findall(r"[A-Za-z][A-Za-z']+", text.lower())
    zh = re.findall(r"[一-鿿]", text)
    bigrams = ["".join(pair) for pair in zip(zh, zh[1:])]
    return [w for w in en if w not in _STOP] + bigrams


def _local_summary(segments: List[dict], summary_language: str) -> dict:
    sents = _sentences(segments)
    if not sents:
        return {"title": "", "summary": "", "highlights": [], "decisions": [],
                "action_items": [], "topics": [], "minutes_markdown": ""}

    freq = Counter(t for s in sents for t in _tokens(s["text"]))
    def score(s):
        toks = _tokens(s["text"])
        return sum(freq[t] for t in toks) / math.sqrt(len(toks) + 1) if toks else 0
    ranked = sorted(range(len(sents)), key=lambda i: score(sents[i]), reverse=True)

    top = sorted(ranked[: min(6, len(sents))])
    summary = " ".join(sents[i]["text"] for i in top[:4])
    highlights = [sents[i]["text"] for i in top]

    decisions = [s["text"] for s in sents if _DECISION.search(s["text"])]
    action_items = [
        {"task": s["text"], "owner": s["speaker"] or "", "due": ""}
        for s in sents if _ACTION_EN.search(s["text"]) or _ACTION_ZH.search(s["text"])
    ][:12]

    # Naive topic split: 2-3 equal chunks in chronological order.
    n = len(sents)
    k = 3 if n >= 6 else (2 if n >= 3 else 1)
    topics = []
    for c in range(k):
        chunk = sents[c * n // k:(c + 1) * n // k]
        if chunk:
            topics.append({"title": chunk[0]["text"][:24], "summary": " ".join(x["text"] for x in chunk)})

    title = sents[top[0]]["text"][:40] if top else "Meeting"
    md = ["# " + title, "", "## 摘要 / Summary", summary, ""]
    md += ["## 重點 / Highlights"] + [f"- {h}" for h in highlights] + [""]
    if decisions:
        md += ["## 決議 / Decisions"] + [f"- {d}" for d in decisions] + [""]
    if action_items:
        md += ["## 行動項目 / Action Items", "", "| 事項 | 負責人 |", "| --- | --- |"]
        md += [f"| {a['task']} | {a['owner']} |" for a in action_items] + [""]
    md += ["## 討論主題 / Topics"]
    for t in topics:
        md += [f"### {t['title']}", t["summary"], ""]

    return {
        "title": title, "summary": summary, "highlights": highlights,
        "decisions": decisions, "action_items": action_items, "topics": topics,
        "minutes_markdown": "\n".join(md),
    }


def summarize(segments: List[dict], summary_language: str = "zh", provider: str = "claude") -> dict:
    if provider == "local":
        result = _local_summary(segments, summary_language)
    else:
        fn = PROVIDERS.get(provider, _via_claude)
        result = _parse_json(fn(_build_prompt(segments, summary_language)))
    result["_provider"] = provider
    return result


def _parse_json(text: str) -> dict:
    """Tolerant JSON extraction in case a model wraps its output."""
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    start, end = text.find("{"), text.rfind("}")
    if start != -1 and end != -1 and end > start:
        try:
            return json.loads(text[start : end + 1])
        except json.JSONDecodeError:
            pass
    return {
        "title": "", "summary": text, "highlights": [], "decisions": [],
        "action_items": [], "topics": [], "minutes_markdown": text,
    }
