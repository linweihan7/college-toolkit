"""Audio helpers: normalise any uploaded recording to 16 kHz mono WAV.

Both Whisper and pyannote work best on 16 kHz mono PCM. We prefer system
ffmpeg (fast, format-agnostic) and fall back to PyAV (pip-installed with
faster-whisper) so the tool still works without a system ffmpeg.
"""
from __future__ import annotations

import shutil
import subprocess
import wave
from pathlib import Path

TARGET_RATE = 16000


def _ffmpeg_convert(src: Path, dst: Path) -> bool:
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        return False
    cmd = [
        ffmpeg, "-y", "-i", str(src),
        "-ac", "1", "-ar", str(TARGET_RATE), "-vn",
        "-c:a", "pcm_s16le", str(dst),
    ]
    proc = subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    if proc.returncode != 0:
        raise RuntimeError(f"ffmpeg failed: {proc.stderr.decode(errors='ignore')[-500:]}")
    return True


def _pyav_convert(src: Path, dst: Path) -> bool:
    try:
        import av  # type: ignore
        import numpy as np
    except Exception:
        return False

    resampler = av.AudioResampler(format="s16", layout="mono", rate=TARGET_RATE)
    chunks = []
    with av.open(str(src)) as container:
        stream = next((s for s in container.streams if s.type == "audio"), None)
        if stream is None:
            raise RuntimeError("no audio stream found in upload")
        for frame in container.decode(stream):
            for rs in resampler.resample(frame):
                chunks.append(rs.to_ndarray().reshape(-1))
    data = np.concatenate(chunks) if chunks else np.zeros(0, dtype="int16")
    with wave.open(str(dst), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(TARGET_RATE)
        wf.writeframes(data.astype("int16").tobytes())
    return True


def to_wav_16k_mono(src: Path, dst: Path) -> Path:
    dst.parent.mkdir(parents=True, exist_ok=True)
    if _ffmpeg_convert(src, dst):
        return dst
    if _pyav_convert(src, dst):
        return dst
    raise RuntimeError(
        "Cannot decode audio: install ffmpeg (`brew install ffmpeg`) or the `av` package."
    )


def enhance_wav(path: Path) -> None:
    """In-place light cleanup of the 16 kHz wav before transcription: high-pass to
    remove low-frequency rumble, then RMS-normalize quiet recordings (capped so we
    don't just amplify noise). Helps the common 'too quiet / distant mic' case."""
    import numpy as np

    try:
        from scipy.signal import butter, sosfilt
    except Exception:
        return
    with wave.open(str(path), "rb") as wf:
        sr, nch, sw, n = wf.getframerate(), wf.getnchannels(), wf.getsampwidth(), wf.getnframes()
        raw = wf.readframes(n)
    a = np.frombuffer(raw, dtype="int16").astype("float32")
    if a.size == 0:
        return
    sos = butter(2, 80.0 / (sr / 2), btype="high", output="sos")
    a = sosfilt(sos, a)
    rms = float(np.sqrt(np.mean(a ** 2)))
    if rms > 1:
        a *= min(0.1 * 32767 / rms, 6.0)   # ~-20 dBFS RMS target, max 6x boost
    a = np.clip(a, -32768, 32767).astype("int16")
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(nch); wf.setsampwidth(sw); wf.setframerate(sr); wf.writeframes(a.tobytes())


def wav_duration(path: Path) -> float:
    with wave.open(str(path), "rb") as wf:
        frames = wf.getnframes()
        rate = wf.getframerate() or TARGET_RATE
    return frames / float(rate)
