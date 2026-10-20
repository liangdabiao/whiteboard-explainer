"""Validated raw and processed narration caches; no filename-only hits."""
from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
from pathlib import Path

from artifacts import atomic_bytes, atomic_json, file_digest, fingerprint
from media import verify
from production import tts_input


VERSION = 1


def cache_hit(path: Path, key: str) -> dict | None:
    try:
        metadata = json.loads(path.with_suffix(path.suffix + ".json").read_text(encoding="utf-8"))
        if metadata["version"] != VERSION or metadata["key"] != key:
            return None
        if metadata["sha256"] != file_digest(path):
            return None
        return verify(path, kind="audio")
    except (OSError, ValueError, KeyError, TypeError):
        return None


def publish(source: Path, target: Path, key: str) -> dict:
    result = verify(source, kind="audio")
    atomic_bytes(target, source.read_bytes())
    atomic_json(target.with_suffix(target.suffix + ".json"), {
        "version": VERSION, "key": key, "sha256": file_digest(source),
    })
    return result


async def get_audio(text: str, config: dict, store: Path, synthesize) -> tuple[Path, float, dict]:
    # 已确认读法预处理只作用于 TTS 输入；缓存按实际提交文本判定
    text = tts_input(text, config["text_version"])
    raw_key = fingerprint({
        "version": VERSION, "text": text,
        **{key: config[key] for key in
           ("provider", "model", "voice", "rate", "text_version", "sdk_version")},
    })
    raw = store / "raw" / f"{raw_key}.mp3"
    generated = cache_hit(raw, raw_key) is None
    if generated:
        store.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix="tts-", dir=store) as td:
            candidate = Path(td) / "raw.mp3"
            await synthesize(text, candidate, config["voice"], rate=config["rate"])
            publish(candidate, raw, raw_key)

    prepared_key = fingerprint({
        "version": VERSION, "raw": file_digest(raw), "trim": config["trim"],
        "codec": "pcm_s16le", "sample_rate": 24000, "channels": 1,
    })
    prepared = store / "prepared" / f"{prepared_key}.wav"
    result = cache_hit(prepared, prepared_key)
    if result is None:
        ffmpeg = shutil.which("ffmpeg")
        if ffmpeg is None:
            raise ValueError("ffmpeg is required for narration preparation")
        with tempfile.TemporaryDirectory(prefix="prepare-", dir=store) as td:
            candidate = Path(td) / "prepared.wav"
            command = [ffmpeg, "-v", "error", "-nostdin", "-i", str(raw)]
            if config["trim"]:
                command += ["-af", "silenceremove=start_periods=1:start_threshold=-45dB:"
                            "start_silence=0.08,areverse,silenceremove=start_periods=1:"
                            "start_threshold=-45dB:start_silence=0.08,areverse"]
            command += ["-ar", "24000", "-ac", "1", "-c:a", "pcm_s16le", str(candidate)]
            subprocess.run(command, check=True, capture_output=True, timeout=120)
            result = publish(candidate, prepared, prepared_key)
    return prepared, result["duration"], {
        "generated": int(generated), "reused": int(not generated),
        "raw_key": raw_key, "prepared_key": prepared_key,
    }
