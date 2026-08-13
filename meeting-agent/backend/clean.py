"""Proofreading rough speech-to-text into cleaner Traditional Chinese.

Two backends:
- "offline": rule-based tidy — needs no API key, always available. Removes filler
  words and stutters, collapses repeats, normalizes punctuation/spacing.
- LLM (claude/openai/gemini): a real rewrite that also fixes homophones. Used
  automatically when an API key is configured.

Used two ways: clean_text() for live captions, clean_lines() for a whole transcript.
"""
from __future__ import annotations

import json
import re
from typing import List

from . import config

SYSTEM = (
    "你是會議逐字稿的即時校對員。輸入是可能不準確、破碎或有錯字的語音辨識文字"
    "（普通話會議，可能夾雜英文）。請改寫成通順、正確的繁體中文，修正同音字與辨識"
    "錯誤、補上適當標點。只輸出校對後的逐字稿本身，不要新增內容、不要回答問題或加入"
    "任何評論。人名、產品名與英文技術詞彙保留原文。"
)


def _via_claude(text: str) -> str:
    from anthropic import Anthropic

    client = Anthropic(api_key=config.ANTHROPIC_API_KEY) if config.ANTHROPIC_API_KEY else Anthropic()
    msg = client.messages.create(
        model=config.CLEAN_MODEL_CLAUDE, max_tokens=2000, system=SYSTEM,
        messages=[{"role": "user", "content": text}],
    )
    return "".join(b.text for b in msg.content if getattr(b, "type", "") == "text").strip()


def _via_openai(text: str) -> str:
    from openai import OpenAI

    client = OpenAI(api_key=config.OPENAI_API_KEY)
    resp = client.chat.completions.create(
        model=config.CLEAN_MODEL_OPENAI,
        messages=[{"role": "system", "content": SYSTEM}, {"role": "user", "content": text}],
    )
    return (resp.choices[0].message.content or "").strip()


def _via_gemini(text: str) -> str:
    from google import genai
    from google.genai import types

    client = genai.Client(api_key=config.GEMINI_API_KEY)
    resp = client.models.generate_content(
        model=config.CLEAN_MODEL_GEMINI, contents=text,
        config=types.GenerateContentConfig(system_instruction=SYSTEM),
    )
    return (resp.text or "").strip()


_PROVIDERS = {"claude": _via_claude, "openai": _via_openai, "gemini": _via_gemini}


# --- Offline rule-based tidy (no API key) ------------------------------------
# Verbal fillers people say while thinking; safe to drop from a written record.
_FILLERS = [
    "嗯嗯", "嗯", "呃", "啊那個", "那個那個", "就是就是", "然後然後",
    "欸", "唉", "喔喔", "哦哦", "齁", "厚",
]
_FILLERS_EN = r"\b(um+|uh+|erm+|hmm+|like,|you know,|i mean,)\b"


def tidy_text(text: str) -> str:
    """Rule-based cleanup: drop fillers, collapse stutters/repeats, fix spacing
    and punctuation. Conservative — it never invents or reinterprets words."""
    t = (text or "").strip()
    if not t:
        return t

    # Immediate character stutters: 我我我 -> 我 ; 這這個 -> 這個
    t = re.sub(r"([一-鿿])\1{1,}", r"\1", t)
    # Repeated two-character words: 然後然後 -> 然後
    t = re.sub(r"([一-鿿]{2})\1+", r"\1", t)
    # English word stutters: the the -> the
    t = re.sub(r"\b(\w+)( \1\b)+", r"\1", t, flags=re.I)

    for f in _FILLERS:
        t = t.replace(f, "")
    t = re.sub(_FILLERS_EN, "", t, flags=re.I)

    # Strip leading discourse fillers ("那個 然後 我們…" -> "我們…"). Only at the
    # start, where they carry no meaning; mid-sentence "然後" is kept.
    t = re.sub(r"^(?:\s*(?:那個|然後|就是|所以說|反正|你知道嗎|對啊|對)\s*[，,]?\s*){1,3}", "", t)

    # Normalize punctuation/spacing.
    t = re.sub(r"\s*,\s*", "，", t) if re.search(r"[一-鿿]", t) else t
    t = re.sub(r"[，,]{2,}", "，", t)
    t = re.sub(r"[。.]{2,}", "。", t)
    t = re.sub(r"\s{2,}", " ", t)
    t = re.sub(r"^[，。、\s]+", "", t)
    t = t.strip()
    # Add a full stop to a substantial Chinese line that lacks end punctuation.
    if t and re.search(r"[一-鿿]$", t) and len(t) >= 6:
        t += "。"
    return t


def tidy_lines(lines: List[str]) -> List[str]:
    return [tidy_text(x) for x in lines]


def clean_text(rough: str, provider: str, context: str = "") -> str:
    """Polish one short passage of live captions (context = last cleaned text)."""
    if not rough.strip():
        return rough
    fn = _PROVIDERS.get(provider)
    if not fn:
        return tidy_text(rough)          # offline fallback — always works
    prompt = (f"前文（僅供銜接參考，不要重複輸出）：\n{context}\n\n" if context else "") + \
        f"請校對這段語音辨識文字：\n{rough}"
    return fn(prompt)


def clean_lines(lines: List[str], provider: str) -> List[str]:
    """Re-write a whole transcript line-by-line, preserving line count/order so
    timestamps and speaker labels stay aligned."""
    fn = _PROVIDERS.get(provider)
    if not fn:
        return tidy_lines(lines)         # offline fallback — always works
    out: List[str] = []
    batch_size = 30
    for i in range(0, len(lines), batch_size):
        batch = lines[i:i + batch_size]
        numbered = "\n".join(f"{j + 1}. {t}" for j, t in enumerate(batch))
        prompt = (
            "以下是普通話會議語音辨識的逐行結果，可能有錯字或辨識錯誤。請逐行校對成通順、"
            "正確的繁體中文，維持完全相同的行數與順序。只回傳一個 JSON 陣列，"
            "每個元素是對應行校對後的文字字串，不要有多餘說明。\n\n" + numbered
        )
        try:
            txt = fn(prompt)
            arr = json.loads(txt[txt.find("["):txt.rfind("]") + 1])
            out.extend(str(x) for x in arr) if len(arr) == len(batch) else out.extend(batch)
        except Exception:
            out.extend(batch)
    return out
