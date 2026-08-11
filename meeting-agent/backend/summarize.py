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
- "highlights": the genuinely important points, ordered MOST IMPORTANT FIRST
  (aim for 4-8). A point counts as important only if it is one of: a decision or
  conclusion; a commitment/action with an owner or deadline; a concrete number,
  metric, date or status; a risk, blocker, problem or disagreement; or a change
  of plan. DO NOT include greetings, small talk, agenda/logistics ("let's kick
  off", "any questions"), or restatements of the topic. Prefer specifics with
  numbers/names over vague statements. Each highlight is one short sentence.
- "decisions": decisions that were actually made (strings). [] if none.
- "action_items": array of {"task","owner","due"} for concrete follow-ups only.
  Use the speaker label or named person as "owner" when attributable, else "".
  "due" is "" if unstated. Do not invent owners or dates.
- "topics": array of {"title","summary"} covering each major discussion topic in order.
- "minutes_markdown": a clean, well-structured Markdown minutes document with
  sections (Summary, Attendees/Speakers if known, Key Points, Decisions,
  Action Items as a table, and a topic-by-topic breakdown).

Ground every point in the transcript — never invent facts, owners, numbers or
dates. If little of substance was said, return fewer highlights rather than
padding with trivia.

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
_RISK = re.compile(r"(blocker|block|issue|problem|risk|concern|delay|fail|unstable|broken|bug|behind|問題|風險|不穩定|延遲|阻礙|故障|錯誤|落後|卡住)", re.I)
_NUM = re.compile(r"(\d|%|百分之|Q[1-4]|OKR|週[一二三四五六日]|星期|下週|下星期|next week|next monday|next friday|by friday|by monday|deadline|月|號)", re.I)
_FILLER = re.compile(r"^\s*(okay|ok|alright|great|thanks|thank you|cool|sure|yeah|hi|hello|good morning|good afternoon|let'?s (kick off|get started|begin)|大家好|你好|哈囉|好的|好啊|謝謝|感謝|嗯|對|是的|沒問題)\b", re.I)


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

    # Salience = keyword-frequency score (used only to break ties).
    freq = Counter(t for s in sents for t in _tokens(s["text"]))
    sal = []
    for s in sents:
        toks = _tokens(s["text"])
        sal.append(sum(freq[t] for t in toks) / math.sqrt(len(toks) + 1) if toks else 0.0)
    max_sal = max(sal) or 1.0

    def importance(i: int) -> float:
        t = sents[i]["text"]
        sc = 0.0
        if _DECISION.search(t):
            sc += 4
        if _ACTION_EN.search(t) or _ACTION_ZH.search(t):
            sc += 3
        if _RISK.search(t):
            sc += 3
        if _NUM.search(t):
            sc += 2
        sc += 0.7 * len(re.findall(r"\b[A-Z]{2,}\b", t))  # acronyms: API, OKR, Q3
        if _FILLER.search(t):
            sc -= 4
        if len(t) < 6:
            sc -= 1
        return sc + sal[i] / max_sal  # tie-break by salience (0..1)

    imp = [importance(i) for i in range(len(sents))]
    order = sorted(range(len(sents)), key=lambda i: imp[i], reverse=True)

    # Highlights: important lines only, de-duplicated, back in chronological order.
    chosen, seen = [], set()
    for i in order:
        if imp[i] <= 0.5:
            continue
        key = re.sub(r"\W", "", sents[i]["text"])[:16]
        if key in seen:
            continue
        seen.add(key)
        chosen.append(i)
        if len(chosen) >= 8:
            break
    if not chosen:  # nothing scored as important — fall back to most salient
        chosen = order[: min(5, len(order))]

    highlights = [sents[i]["text"] for i in sorted(chosen, key=lambda i: sents[i]["start"])]
    summary = " ".join(sents[i]["text"] for i in sorted(chosen[:4], key=lambda i: sents[i]["start"]))

    decisions, seen_d = [], set()
    for s in sents:
        if _DECISION.search(s["text"]) and s["text"][:16] not in seen_d:
            seen_d.add(s["text"][:16])
            decisions.append(s["text"])
    action_items, seen_a = [], set()
    for s in sents:
        if (_ACTION_EN.search(s["text"]) or _ACTION_ZH.search(s["text"])) and not _FILLER.search(s["text"]):
            if s["text"][:16] in seen_a:
                continue
            seen_a.add(s["text"][:16])
            action_items.append({"task": s["text"], "owner": s["speaker"] or "", "due": ""})
    action_items = action_items[:12]

    # Naive topic split: 2-3 equal chunks in chronological order.
    n = len(sents)
    k = 3 if n >= 6 else (2 if n >= 3 else 1)
    topics = []
    for c in range(k):
        chunk = sents[c * n // k:(c + 1) * n // k]
        if chunk:
            topics.append({"title": chunk[0]["text"][:24], "summary": " ".join(x["text"] for x in chunk)})

    title = sents[order[0]]["text"][:40] if order else "Meeting"
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
