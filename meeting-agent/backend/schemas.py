"""Pydantic models shared across the API."""
from __future__ import annotations

from typing import List, Literal, Optional

from pydantic import BaseModel, Field


class ProcessOptions(BaseModel):
    title: str = ""
    engine: Literal["local", "cloud"] = "local"
    # "auto" lets Whisper decide; otherwise force one of the supported languages.
    language: Literal["auto", "en", "zh"] = "auto"
    diarize: bool = True
    num_speakers: Optional[int] = None  # hint; None = auto-detect
    # Default to Traditional Chinese summaries (this app is zh-Hant first).
    summary_language: Literal["auto", "en", "zh"] = "zh"
    # Which AI writes the summary/highlights. "" = server picks best available.
    summary_provider: Literal["", "claude", "openai", "gemini", "local"] = ""
    # Domain vocabulary / names to bias the transcriber (proper nouns, jargon).
    vocabulary: str = ""


class Word(BaseModel):
    start: float
    end: float
    word: str


class Segment(BaseModel):
    start: float
    end: float
    text: str
    speaker: Optional[str] = None
    words: List[Word] = Field(default_factory=list)


class ActionItem(BaseModel):
    task: str
    owner: str = ""
    due: str = ""


class Topic(BaseModel):
    title: str
    summary: str


class Summary(BaseModel):
    title: str = ""
    summary: str = ""
    highlights: List[str] = Field(default_factory=list)
    decisions: List[str] = Field(default_factory=list)
    action_items: List[ActionItem] = Field(default_factory=list)
    topics: List[Topic] = Field(default_factory=list)
    minutes_markdown: str = ""


class MeetingResult(BaseModel):
    language: str = ""
    duration: float = 0.0
    engine: str = ""
    diarized: bool = False
    speakers: List[str] = Field(default_factory=list)
    segments: List[Segment] = Field(default_factory=list)
    summary: Optional[Summary] = None
