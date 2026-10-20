"""Pad scene PCM to include an explicit hold and whole video frames."""
from __future__ import annotations

import io
import math
import wave
from pathlib import Path

from artifacts import atomic_bytes


def silent_scene(path: Path, seconds: float) -> None:
    if not math.isfinite(seconds) or seconds <= 0:
        raise ValueError("A silent drawing scene needs a positive finite duration")
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as audio:
        audio.setnchannels(1)
        audio.setsampwidth(2)
        audio.setframerate(24000)
        audio.writeframes(b"\0\0" * math.ceil(seconds * 24000))
    atomic_bytes(path, buffer.getvalue())


def pad_scene(path: Path, hold: float, fps: int, tail_pad: float = 0) -> dict:
    if (not math.isfinite(hold) or not math.isfinite(tail_pad)
            or hold < 0 or tail_pad < 0 or not 1 <= fps <= 120):
        raise ValueError("Scene timing requires finite nonnegative padding and valid fps")
    with wave.open(str(path), "rb") as audio:
        rate, channels, width = audio.getframerate(), audio.getnchannels(), audio.getsampwidth()
        data = audio.readframes(audio.getnframes())
    if channels != 1 or width != 2 or not data:
        raise ValueError("Scene padding requires nonempty mono 16-bit PCM")
    samples = len(data) // 2
    padded = samples + math.ceil((hold + tail_pad) * rate)
    frames = max(1, math.ceil(padded / rate * fps - 1e-9))
    target = max(padded, math.ceil(frames * rate / fps - 1e-9))
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as audio:
        audio.setnchannels(1)
        audio.setsampwidth(2)
        audio.setframerate(rate)
        audio.writeframes(data + b"\0\0" * (target - samples))
    atomic_bytes(path, buffer.getvalue())
    return {"narration_duration": samples / rate, "hold": hold,
            "tail_pad": tail_pad, "fps": fps, "frames": frames}
