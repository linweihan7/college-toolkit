"""AI proofreading of rough speech-to-text into clean Traditional Chinese.

Used two ways:
- live:  clean_text() polishes the rolling live captions while recording.
- final: clean_lines() re-writes the whole transcript line-by-line after a meeting.

Uses each provider's fast model (Haiku / gpt-4o-mini / Gemini Flash) for low latency.
"""
from __future__ import annotations

import json
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


def clean_text(rough: str, provider: str, context: str = "") -> str:
    """Polish one short passage of live captions (context = last cleaned text)."""
    fn = _PROVIDERS.get(provider)
    if not fn or not rough.strip():
        return rough
    prompt = (f"前文（僅供銜接參考，不要重複輸出）：\n{context}\n\n" if context else "") + \
        f"請校對這段語音辨識文字：\n{rough}"
    return fn(prompt)


def clean_lines(lines: List[str], provider: str) -> List[str]:
    """Re-write a whole transcript line-by-line, preserving line count/order so
    timestamps and speaker labels stay aligned."""
    fn = _PROVIDERS.get(provider)
    if not fn:
        return lines
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
