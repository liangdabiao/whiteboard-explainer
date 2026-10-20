"""Local metadata and complete-decode checks, independent of other skills."""
from __future__ import annotations

import json
import math
import shutil
import subprocess
from fractions import Fraction
from pathlib import Path


def verify(path: Path, *, kind: str | None = None, decode: bool = True) -> dict:
    if not path.is_file() or not path.stat().st_size:
        raise ValueError(f"Media file is missing or empty: {path}")
    ffprobe = shutil.which("ffprobe")
    if ffprobe is None:
        raise ValueError("Local ffprobe is required for media metadata")
    result = subprocess.run(
        [ffprobe, "-v", "error", "-show_format", "-show_streams", "-of", "json", str(path)],
        capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=120,
    )
    if result.returncode:
        raise ValueError(f"Media probe failed: {path}")
    data = json.loads(result.stdout)
    streams = data.get("streams", [])
    kinds = {s.get("codec_type") for s in streams}
    if not kinds.intersection({"audio", "video"}) or (kind and kind not in kinds):
        raise ValueError(f"Required media stream is absent: {path}")
    raw = data.get("format", {}).get("duration")
    if raw is None:
        durations = [float(s["duration"]) for s in streams if s.get("duration") not in (None, "N/A")]
        raw = max(durations) if durations else 0
    duration = float(raw)
    if not math.isfinite(duration) or duration <= 0:
        raise ValueError(f"Media duration must be positive and finite: {path}")
    if decode:
        ffmpeg = shutil.which("ffmpeg")
        if ffmpeg is None:
            raise ValueError("Local ffmpeg is required for complete decoding")
        decoded = subprocess.run(
            [ffmpeg, "-v", "error", "-xerror", "-nostdin", "-i", str(path),
             "-map", "0:a?", "-map", "0:v?", "-f", "null", "-"],
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=120,
        )
        if decoded.returncode or decoded.stderr.strip():
            raise ValueError(f"Complete media decode failed: {path}")
    result_data: dict = {"duration": duration, "streams": sorted(k for k in kinds if k),
                         "metadata": "PASS", "decode": "PASS" if decode else "NOTRUN"}
    videos = [s for s in streams if s.get("codec_type") == "video"]
    if videos:
        video = videos[0]
        try:
            fps = float(Fraction(video.get("avg_frame_rate") or video["r_frame_rate"]))
        except (ValueError, ZeroDivisionError) as exc:
            raise ValueError("Video has an invalid frame rate") from exc
        if fps <= 0 or int(video["width"]) <= 0 or int(video["height"]) <= 0:
            raise ValueError("Video has an invalid frame rate or dimensions")
        result_data["video"] = {"fps": fps, "width": int(video["width"]), "height": int(video["height"])}
    return result_data


def concat_manifest(parts: list[Path], target: Path) -> Path:
    """ffmpeg concat demuxer manifest beside the output; the caller deletes it."""
    manifest = target.parent / (target.name + ".concat.txt")
    manifest.write_text("".join(
        "file '" + p.resolve().as_posix().replace("'", "'\\''") + "'\n"
        for p in parts), encoding="utf-8")
    return manifest
