"""Local narration preparation shared by approval and production CLIs."""
from __future__ import annotations

import importlib
import hashlib
import json
import math
import os
import re
import shutil
import subprocess
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

from PIL import Image, ImageFont

from teaching import teaching_plan

try:
    import yaml  # type: ignore[import-untyped]
except ImportError:
    yaml = None  # type: ignore[assignment]


def load_document_and_hash(path: Path):
    data = path.read_bytes()
    text = data.decode("utf-8-sig")
    if path.suffix.lower() in (".yaml", ".yml"):
        if yaml is None:
            raise ValueError("YAML input requires PyYAML; JSON input needs no extra parser")
        spec = yaml.safe_load(text)
    else:
        spec = json.loads(text)
    return spec, hashlib.sha256(data).hexdigest()


def load_document(path: Path):
    return load_document_and_hash(path)[0]


def load_spec(path: Path) -> dict:
    return load_spec_and_hash(path)[0]


def load_spec_and_hash(path: Path) -> tuple[dict, str]:
    spec, digest = load_document_and_hash(path)
    if not isinstance(spec, dict):
        raise ValueError("The production input must be an object")
    return spec, digest


def declared_path(root: Path, value: str, name: str) -> Path:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a path string")
    resolved = (root / value).resolve()
    if not resolved.is_relative_to(root.resolve()):
        raise ValueError(f"{name} must stay inside this project")
    return resolved


TEXT_VERSION = 2


def tts_input(text: str, version: int) -> str:
    """Confirmed read-aloud preprocessing applied only at the TTS input boundary."""
    if version == 1:
        return text
    if version == 2:
        return " ".join(text.replace("_", " ").split())
    raise ValueError(f"Unsupported text preprocessing version: {version}")


def narration_config(spec: dict, mode: str = "standard", rate: str | None = None) -> dict:
    default_voice = "zh-CN-YunxiNeural"
    if mode == "scene":
        default_voice = "en-US-JennyNeural" if spec.get("lang") == "en" else "zh-CN-XiaoyiNeural"
    default_rate = "+22%" if mode == "fast" else "+0%"
    if mode == "scene" and "speed" in spec and "rate" not in spec:
        speed = float(spec["speed"])
        if not math.isfinite(speed):
            raise ValueError("speed must be finite")
        default_rate = f"{int(round((speed - 1) * 100)):+d}%"
    text_version = spec.get("text_version", TEXT_VERSION)
    if isinstance(text_version, bool) or text_version not in (1, 2):
        raise ValueError("text_version must be 1 or 2")
    try:
        sdk_version = version("edge-tts")
    except PackageNotFoundError:
        sdk_version = "unavailable"
    config = {
        "version": 1,
        "provider": spec.get("tts_provider", "edge"),
        "model": spec.get("tts_model", "edge-tts"),
        "voice": spec.get("voice", default_voice),
        "rate": rate or spec.get("rate", default_rate),
        "trim": mode == "fast",
        "text_version": text_version,
        "sdk_version": sdk_version,
    }
    if config["provider"] != "edge" or config["model"] != "edge-tts":
        raise ValueError("This CLI supports only the edge / edge-tts backend")
    if not isinstance(config["voice"], str) or not config["voice"].strip():
        raise ValueError("voice must be a nonempty string")
    if not isinstance(config["rate"], str) or not re.fullmatch(r"[+-]\d+%", config["rate"]):
        raise ValueError("rate must be a signed percentage, such as +15%")
    if not -90 <= int(config["rate"][:-1]) <= 300:
        raise ValueError("rate must be between -90% and +300%")
    return config


def positive(value, name: str) -> float:
    if isinstance(value, bool):
        raise ValueError(f"{name} must be a positive finite number")
    number = float(value)
    if not math.isfinite(number) or number <= 0:
        raise ValueError(f"{name} must be a positive finite number")
    return number


def normalize_canvas(value) -> list[int]:
    if (not isinstance(value, list) or len(value) != 2
            or any(isinstance(v, bool) or not isinstance(v, int)
                   or not 2 <= v <= 1280 or v % 2 for v in value)):
        raise ValueError("canvas needs two even dimensions within 2..1280")
    return value


def spoken_text(region: dict, source: str = "annotation") -> str:
    text = region.get("spoken_text", region.get(source, ""))
    if not isinstance(text, str):
        raise ValueError("spoken_text must be a string")
    return text.strip()


def validate_spec(spec: dict, root: Path, mode: str, allow_empty: bool = False) -> None:
    scenes = spec.get("scenes")
    if not isinstance(scenes, list) or (not scenes and not allow_empty):
        raise ValueError("scenes must be a nonempty array")
    gap = spec.get("gap", 0.35)
    if isinstance(gap, bool) or not math.isfinite(float(gap)) or float(gap) < 0:
        raise ValueError("gap must be a nonnegative finite number")
    normalize_canvas(spec.get("canvas", [1280, 720]))
    fps = spec.get("fps", 24)
    if isinstance(fps, bool) or not isinstance(fps, int) or not 1 <= fps <= 120:
        raise ValueError("fps must be an integer within 1..120")
    tail = spec.get("tail_pad", 0)
    if (isinstance(tail, bool) or not isinstance(tail, (int, float))
            or not math.isfinite(tail) or not 0 <= tail <= 120):
        raise ValueError("tail_pad must be within 0..120 seconds")
    if not isinstance(spec.get("idea", ""), str):
        raise ValueError("idea must be a string")
    audio_dir = spec.get("audio_dir", "audio/narration")
    declared_path(root, audio_dir, "audio_dir")
    ids = set()
    for scene in scenes:
        if not isinstance(scene, dict):
            raise ValueError("Every scene must be an object")
        sid = scene.get("id")
        if not isinstance(sid, str) or not re.fullmatch(r"[A-Za-z0-9_-]+", sid) or sid in ids:
            raise ValueError("Scene ids must be unique, nonempty and path-safe")
        ids.add(sid)
        if mode == "scene":
            if not isinstance(scene.get("text"), str) or not scene["text"].strip():
                raise ValueError(f"{sid}: text must be a nonempty string")
            if not spoken_text(scene, "text"):
                raise ValueError(f"{sid}: text must be nonempty")
            continue
        image = scene.get("image")
        if not isinstance(image, str):
            raise ValueError(f"{sid}: image path is required")
        try:
            with Image.open(declared_path(root, image, f"{sid}: image")) as im:
                im.verify()
        except (OSError, ValueError) as exc:
            raise ValueError(f"{sid}: image cannot be read") from exc
        if "audio" in scene:
            declared_path(root, scene["audio"], f"{sid}: audio")
        if "duration" in scene:
            positive(scene["duration"], f"{sid}: duration")
        regions = scene.get("regions", [])
        if not isinstance(regions, list):
            raise ValueError(f"{sid}: regions must be an array")
        for region in regions:
            if not isinstance(region, dict):
                raise ValueError(f"{sid}: region must be an object")
            if not isinstance(region.get("annotation", ""), str):
                raise ValueError(f"{sid}: annotation must be a string")
            spoken_text(region)
            box = region.get("box", region.get("box_2d"))
            boxes = box if isinstance(box, list) and box and isinstance(box[0], (list, dict)) else [box]
            for b in boxes:
                if isinstance(b, dict):
                    b = [b.get(k) for k in ("ymin", "xmin", "ymax", "xmax")]
                if not isinstance(b, list) or len(b) != 4:
                    raise ValueError(f"{sid}: box requires four normalized coordinates")
                if any(isinstance(v, bool) or not isinstance(v, (int, float))
                       or not math.isfinite(v) or not 0 <= v <= 1000 for v in b):
                    raise ValueError(f"{sid}: box coordinates must be within 0..1000")
                y0, x0, y1, x1 = b
                if y0 >= y1 or x0 >= x1:
                    raise ValueError(f"{sid}: box must have positive width and height")
    if spec.get("font"):
        try:
            ImageFont.truetype(str(declared_path(root, spec["font"], "font")), 24)
        except OSError as exc:
            raise ValueError("The requested font cannot be loaded") from exc
    teaching_plan(spec)


def media_tools() -> dict:
    tools = {}
    for name in ("ffmpeg", "ffprobe"):
        path = shutil.which(name)
        if path is None:
            raise ValueError("Local ffmpeg and ffprobe are required")
        tools[name] = path
    result = subprocess.run([tools["ffmpeg"], "-hide_banner", "-encoders"],
                            capture_output=True, text=True, errors="replace", timeout=30)
    if result.returncode or "libx264" not in result.stdout:
        raise ValueError("ffmpeg must support libx264")
    probe = subprocess.run([tools["ffprobe"], "-version"], capture_output=True,
                           text=True, errors="replace", timeout=30)
    if probe.returncode or "ffprobe" not in probe.stdout:
        raise ValueError("ffprobe is not executable")
    return tools


def local_tools() -> dict:
    tools = media_tools()
    try:
        importlib.import_module("edge_tts")
    except ImportError as exc:
        raise ValueError("The selected backend requires an importable edge-tts SDK") from exc
    return tools


CAPABILITIES = ("boards", "tts", "apiz", "render")


def capability_check(name: str) -> str:
    """Check the local conditions a selected capability needs.

    Returns what was verified. Credential checks prove presence only:
    values are never printed and connectivity is never claimed.
    """
    if name == "boards":
        importlib.import_module("PIL")
        return "Pillow importable"
    if name == "tts":
        try:
            importlib.import_module("edge_tts")
        except ImportError as exc:
            raise ValueError("edge-tts SDK is not importable") from exc
        return "edge-tts SDK importable (connectivity not verified)"
    if name == "render":
        media_tools()
        return "ffmpeg/ffprobe/libx264 available"
    if name == "apiz":
        if not (os.environ.get("APIZ_API_KEY")
                or (Path.home() / ".config/apiz/config.toml").is_file()):
            raise ValueError("apiz requires APIZ_API_KEY or ~/.config/apiz/config.toml")
        return "apiz credential present (value and connectivity not verified)"
    raise ValueError(f"Unknown capability: {name}")


def inspection_report(spec: dict, root, mode: str = "standard",
                      rate: str | None = None, runtime: bool = False) -> dict:
    config = narration_config(spec, mode, rate)
    validate_spec(spec, Path(root), mode, allow_empty=not runtime)
    if runtime:
        local_tools()
    return {"status": "PASS", "config": config,
            "teaching_plan": teaching_plan(spec),
            "canvas": spec.get("canvas", [1280, 720]),
            "fps": spec.get("fps", 24),
            "scenes": [scene["id"] for scene in spec["scenes"]],
            "remote": "NOTRUN",
            "runtime": "PASS" if runtime else "NOTRUN"}


def print_inspection(spec: dict, root, mode: str = "standard",
                     rate: str | None = None, runtime: bool = False) -> None:
    print(json.dumps(inspection_report(spec, root, mode, rate, runtime),
                     ensure_ascii=True))


def print_design(spec: dict) -> None:
    print(json.dumps({"status": "PASS", "stage": "DESIGN",
                      "teaching_plan": teaching_plan(spec)}, ensure_ascii=True))
