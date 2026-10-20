"""Shared fixtures for CLI-boundary regression tests; all synthesis stays offline."""
from __future__ import annotations

import subprocess
import sys
import tempfile
import wave
from pathlib import Path

from PIL import Image

SCRIPTS = Path(__file__).resolve().parent


def temp_project(case) -> Path:
    case.temp = tempfile.TemporaryDirectory()
    case.addCleanup(case.temp.cleanup)
    root = Path(case.temp.name)
    Image.new("RGB", (64, 36), "white").save(root / "board.png")
    return root


def cli(script, *args, input_text=None):
    return subprocess.run(
        [sys.executable, str(SCRIPTS / script), *map(str, args)],
        capture_output=True, text=True, encoding="utf-8", input=input_text,
    )


def write_wav(path: Path, frames: int, *, rate: int = 24000,
              tone_frames: int | None = None) -> None:
    tone_frames = frames if tone_frames is None else tone_frames
    with wave.open(str(path), "wb") as stream:
        stream.setnchannels(1)
        stream.setsampwidth(2)
        stream.setframerate(rate)
        stream.writeframes(b"\xe8\x03" * tone_frames + b"\0\0" * (frames - tone_frames))


def fake_tts(requests, *, frames: int = 6000):
    """edge_tts.Communicate substitute writing a deterministic WAV."""
    def communicate(text, voice, rate):
        requests.append((text, voice, rate))

        class Request:
            async def save(self, filename):
                write_wav(Path(filename), frames)
        return Request()
    return communicate
