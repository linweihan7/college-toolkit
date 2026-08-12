# Meeting Scribe

A precise, professional meeting recorder and minute-taker for **Mandarin + English**
meetings. Records audio (in-room or online calls), transcribes every word,
labels who said what, and produces highlights, decisions, action items and a
clean minutes document.

Everything runs **on your own machine**. Audio only leaves the device if you
deliberately choose the *Cloud API* transcription engine.

## What it does

1. **Record** from your microphone, and optionally the computer/tab audio of an
   online call — or drop in an existing audio/video file.
2. **Live captions** (optional, on by default): while you record, short audio
   windows stream to a fast local model and captions appear within a few seconds
   — rough by design. The accurate transcript is produced by the full pass below.
   With an AI key set, tick **AI 即時校對** to have a fast LLM proofread those
   rough captions into clean Traditional Chinese live. After a meeting, the
   **✨ AI 校對逐字稿** button re-writes the whole transcript the same way.
3. **Transcribe** the full recording after the meeting, with a choice of engine:
   - **Local Whisper** (`faster-whisper large-v3`) — offline, private, free.
   - **Cloud API** (OpenAI) — no local model, chunked to handle long meetings.
   Both handle Mandarin/English code-switching.
3. **Label speakers** with on-device diarization (`pyannote`).
4. **Summarize & highlight** with Claude: executive summary, key highlights,
   decisions, action items (with owners), topic breakdown, and ready-to-share
   Markdown minutes.
5. **Review & export** in a local web UI — searchable transcript with
   click-to-seek timestamps, highlights, and `.md` / `.txt` export.

## Setup

Requires Python 3.9+. **ffmpeg is optional** — faster-whisper ships its own
audio decoder, so recording + local transcription work without it. Install it
only if you feed in an unusual container format and hit a decode error:

```bash
brew install ffmpeg
```

Then, from this folder:

```bash
cp .env.example .env      # add your keys (see below)
./run.sh                  # first run creates a venv and installs core deps
```

Open **http://localhost:8000**.

### Keys / features (all optional — the sidebar shows what's active)

| Feature | Needs |
| --- | --- |
| Highlights & minutes | `ANTHROPIC_API_KEY` in `.env` |
| Cloud transcription | `OPENAI_API_KEY` in `.env` |
| Local transcription  | `pip install -r requirements-local.txt` |
| Speaker labels | `pip install -r requirements-local.txt` + `HUGGINGFACE_TOKEN` (accept terms for `pyannote/speaker-diarization-3.1` and `pyannote/segmentation-3.0`) |

To enable the local engine and speaker labels:

```bash
./.venv/bin/pip install -r requirements-local.txt
```

### Summaries (highlights / minutes)

Summaries work **out of the box** with a built-in offline extractive summarizer
(no key, fully local) — good for a quick digest. For high-quality highlights,
decisions and action-item attribution, pick an AI in the **摘要 AI** dropdown:

- **Claude** — set `ANTHROPIC_API_KEY`
- **GPT** — set `OPENAI_API_KEY`
- **Gemini** — set `GEMINI_API_KEY` (Google AI Studio issues a **free** key, no
  card: https://aistudio.google.com/apikey)

The server auto-selects the best available: your chosen provider → any keyed AI →
offline. Each meeting records which AI produced its summary.

Already recorded a meeting before adding a key? Open it, pick an AI, and click
**「生成摘要」** — it summarizes the existing transcript, no re-recording needed.

The first local transcription downloads the Whisper model (~1.5 GB for
`large-v3`); set `LOCAL_WHISPER_MODEL=medium` in `.env` for a lighter/faster model.

## Notes

- **Recording others is subject to consent laws.** Get participants' agreement
  before recording a meeting.
- Transcription happens **after** you stop recording, so the model sees full
  context — this maximizes accuracy on "every word."
- Meetings, audio and transcripts are stored under `./data/` (git-ignored).

## Project layout

```
backend/
  main.py        FastAPI app + REST API + serves the UI
  pipeline.py    orchestration: audio → transcribe → diarize → summarize
  transcribe.py  local (faster-whisper) + cloud (OpenAI) engines
  diarize.py     pyannote diarization + speaker/transcript merge
  summarize.py   Claude summary/highlights/minutes (JSON)
  audio.py       normalise uploads to 16 kHz mono WAV (ffmpeg / PyAV)
  storage.py     SQLite persistence
frontend/        single-page web UI (no build step)
```
