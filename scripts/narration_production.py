"""配音生产：三个用途入口共享批准快照、运行生命周期与发布协议。"""
from __future__ import annotations

import asyncio
import copy
import subprocess
from dataclasses import dataclass
from pathlib import Path

from artifacts import atomic_bytes, atomic_json, file_lock
from audio_timing import pad_scene, silent_scene
from media import concat_manifest
from narration_cache import get_audio
from narration_runs import NarrationRun, relative
from production import inspection_report, load_spec, load_spec_and_hash, spoken_text
from user_gates import GateError, authorize_preview, require, require_spec_snapshot

try:
    import edge_tts
except ImportError:
    edge_tts = None  # type: ignore[assignment]


@dataclass(frozen=True)
class _Input:
    root: Path
    source: Path
    source_sha256: str
    spec: dict
    config: dict


def _prepare(spec: dict | Path, root: Path | None, mode: str,
             rate: str | None = None, *, preview: bool = False) -> _Input:
    source = None
    source_sha256 = None
    if isinstance(spec, Path):
        source = spec.resolve()
        root = source.parent
        if not preview:
            require(root, "G3", source)
        document, source_sha256 = load_spec_and_hash(source)
    else:
        if root is None:
            raise ValueError("A project root is required for a parsed narration input")
        root = root.resolve()
        document = spec
    if mode == "fast" and rate is not None and rate != document.get("rate", "+22%"):
        require(root, "G3")
        raise GateError("BLOCKED: --rate must match the approved spec rate")
    if not preview:
        source, source_sha256, document = require_spec_snapshot(root, document, mode, rate)
    if source is None or source_sha256 is None:
        raise ValueError("A source file is required for a preview")
    report = inspection_report(document, root, mode, rate, runtime=True)
    config = report["config"]
    if preview:
        texts = [spoken_text(scene, "text") for scene in document["scenes"]]
        print(f"Preview: voice={config['voice']}, rate={config['rate']}, texts={texts}")
        authorize_preview(root, texts)
    return _Input(root, source, source_sha256, document, config)


async def produce_regions(spec: dict | Path, root: Path | None = None, *,
                          mode: str = "standard", rate: str | None = None,
                          dry: bool = False) -> dict:
    """生成 region 音轨与 plan；字典输入保留旧 build() 调用方式。"""
    if dry:
        if isinstance(spec, Path):
            root = spec.resolve().parent
            spec = load_spec(spec)
        if root is None:
            raise ValueError("A project root is required for a parsed narration input")
        report = inspection_report(spec, root, mode, rate)
        return {"config": report["config"], "scenes": spec["scenes"]}
    prepared = _prepare(spec, root, mode, rate)
    return await _produce(prepared, output=None)


async def produce_scenes(source: Path, *, output: Path) -> dict:
    """生成 scene.text 音轨与 timeline，返回现有 CLI 的清单摘要。"""
    prepared = _prepare(source, None, "scene")
    return await _produce(prepared, output=output.resolve())


async def preview_sentence(source: Path, *, output: Path) -> dict:
    """单句试听；在共享运行协议内保留 G2 与额外单句授权。"""
    prepared = _prepare(source, None, "scene", preview=True)
    return await _produce(prepared, output=output.resolve())


async def _produce(prepared: _Input, *, output: Path | None) -> dict:
    root, spec, config = prepared.root, prepared.spec, prepared.config
    target = root / "plan.json" if output is None else output / "timeline.json"
    if prepared.source.resolve() == target.resolve():
        raise ValueError(f"Use a separate narration input; {target.name} is generated")
    with file_lock(root / ".narration-cache" / "production.lock"):
        current = NarrationRun(root, spec, config, prepared.source, output,
                               source_sha256=prepared.source_sha256)
        try:
            payload: dict | list
            if output is None:
                payload = await _build_regions(spec, root, config, current)
            else:
                payload = await _build_scenes(spec, root, config, current)
            return _publish(current, payload, target)
        except BaseException:
            current.fail()
            raise


def _publish(current: NarrationRun, payload: dict | list, target: Path) -> dict:
    root = current.root
    if isinstance(payload, dict):
        archived_plan = copy.deepcopy(payload)
        for scene in archived_plan["scenes"]:
            scene["image"] = relative(root / scene["image"], current.directory)
            if scene.get("audio"):
                scene["audio"] = relative(root / scene["audio"], current.directory)
        payload["narration"] = current.complete(archived_plan)
        payload["narration"]["fps"] = payload["fps"]
        atomic_json(target, payload)
        print(f"写出 {target}")
        return payload
    archived_timeline = [{**item, "file": relative(root / item["file"], current.directory),
                          "manifest": "manifest.json"} for item in payload]
    summary = current.complete(archived_timeline, "timeline.json")
    atomic_json(target, payload)
    return summary


async def _build_scenes(spec: dict, root: Path, config: dict, current: NarrationRun) -> list:
    timeline = []
    for scene in spec["scenes"]:
        sid = scene["id"]
        text = spoken_text(scene, "text")
        out_path = current.directory / f"{sid}.wav"
        cached, _, facts = await get_audio(text, config, root / ".narration-cache", tts)
        atomic_bytes(out_path, cached.read_bytes())
        timing = pad_scene(out_path, float(scene.get("hold", 0)), spec.get("fps", 24),
                           float(spec.get("tail_pad", 0)))
        current.record(sid, out_path, [], [facts], timing)
        timeline.append({
            "id": sid, "file": relative(out_path, root), "text": scene["text"],
            "spoken_text": text, "seconds": timing["frames"] / timing["fps"], **timing,
            "manifest": relative(current.manifest, root),
        })
    return timeline


def run(cmd: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, check=True, capture_output=True,
                          encoding="utf-8", errors="replace")


def probe_duration(path: Path) -> float:
    out = run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
               "-of", "csv=p=0", str(path)])
    return float(out.stdout.strip())


async def tts(text: str, out: Path, voice: str, rate: str = "+0%") -> None:
    """edge-tts 偶发 NoAudioReceived/网络抖动，重试 3 次。"""
    if edge_tts is None:
        raise ValueError("The selected backend requires edge-tts")
    last = None
    for attempt in range(3):
        try:
            com = edge_tts.Communicate(text, voice, rate=rate)
            await com.save(str(out))
            if out.exists() and out.stat().st_size > 1000:
                return
            raise RuntimeError(f"TTS 产物过小: {out.stat().st_size if out.exists() else 0}B")
        except Exception as exc:  # noqa: BLE001
            last = exc
            await asyncio.sleep(1.5 * (attempt + 1))
    raise RuntimeError(f"TTS 三次失败: {text[:20]}… -> {last}") from last


def make_gap(out_dir: Path, seconds: float) -> Path:
    gap = out_dir / ".gap.wav"
    if not gap.exists():
        run(["ffmpeg", "-y", "-f", "lavfi", "-i",
             f"anullsrc=r=24000:cl=mono", "-t", f"{seconds}",
             "-c:a", "pcm_s16le", str(gap)])
    return gap


def concat(parts: list[Path], out: Path) -> None:
    lst = concat_manifest(parts, out)
    run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(lst),
         "-ar", "24000", "-ac", "1", "-c:a", "pcm_s16le", str(out)])
    lst.unlink()


async def _build_regions(spec: dict, root: Path, config: dict, current: NarrationRun) -> dict:
    gap = float(spec.get("gap", 0.35))
    audio_dir = current.directory
    gap_path = make_gap(audio_dir, gap) if gap else None

    plan = {
        "idea": spec.get("idea", ""),
        "canvas": spec.get("canvas", [1280, 720]),
        "fps": spec.get("fps", 24),
        "teaching": spec.get("teaching", False),
        "scenes": [],
    }
    audio_mode = spec.get("teaching", False) or any(
        spoken_text(region) for scene in spec["scenes"] for region in scene.get("regions", [])
    )

    for scene in spec["scenes"]:
        sid = scene["id"]
        regions = scene.get("regions") or []
        annotations = [spoken_text(r) for r in regions]
        # 无 annotation 的 region（纯图形）也要有窗口：用空串 TTS 会失败，改为复用时长 0
        spoken = [(i, a) for i, a in enumerate(annotations) if a]

        scene_audio = audio_dir / f"{sid}.wav"
        windows: dict[int, tuple[float, float]] = {}
        scene_facts = []
        timing = {}

        if spoken:
            # 1. 逐子句 TTS
            clips: list[tuple[int, Path, float]] = []
            for k, (idx, text) in enumerate(spoken):
                clip, duration, facts = await get_audio(text, config, root / ".narration-cache", tts)
                print(f"  TTS {sid} r{k:02d}: generated={facts['generated']} reused={facts['reused']}")
                scene_facts.append(facts)
                clips.append((idx, clip, duration))
            # 2. 累积时间窗：region i 的窗口 = 它自己分片起点 → 下一个分片结束（含尾部 gap）
            cursor = 0.0
            for j, (idx, clip, dur) in enumerate(clips):
                start = cursor
                end = cursor + dur + (gap if j < len(clips) - 1 else 0)
                windows[idx] = (round(start, 3), round(end, 3))
                cursor = end
            # 3. 拼接整拍音轨（分片 + 间隔）
            parts: list[Path] = []
            for j, (idx, clip, dur) in enumerate(clips):
                parts.append(clip)
                if j < len(clips) - 1 and gap_path:
                    parts.append(gap_path)
            if parts:
                concat(parts, scene_audio)
                total = probe_duration(scene_audio)
                # 尾部窗口 clamp 到实际音轨长度
                for idx, (s, e) in windows.items():
                    windows[idx] = (s, min(e, total))
                timing = pad_scene(scene_audio, float(scene.get("hold", 0)),
                                   plan["fps"], float(spec.get("tail_pad", 0)))
        elif audio_mode:
            silent_scene(scene_audio, float(scene.get("duration", 8)))
            timing = pad_scene(scene_audio, float(scene.get("hold", 0)),
                               plan["fps"], float(spec.get("tail_pad", 0)))

        out_scene = {"id": sid, "image": scene["image"]}
        out_scene.update(timing)
        for key in ("role", "visual"):
            if key in scene:
                out_scene[key] = scene[key]
        if windows or timing:
            out_scene["audio"] = relative(scene_audio, root)
        elif scene.get("duration"):
            out_scene["duration"] = scene["duration"]

        out_regions = []
        for i, r in enumerate(regions):
            entry = {"label": r.get("label", f"r{i}"), "box": r.get("box", r.get("box_2d"))}
            if "annotation" in r:
                entry["annotation"] = r["annotation"]
            if "spoken_text" in r:
                entry["spoken_text"] = r["spoken_text"]
            if i in windows:
                s, e = windows[i]
                entry["start"], entry["end"] = s, e
            elif r.get("annotation"):
                entry["annotation"] = r["annotation"]  # 降级为估算档
            out_regions.append(entry)
        out_scene["regions"] = out_regions
        plan["scenes"].append(out_scene)
        current.record(sid, scene_audio if windows or timing else None, out_regions, scene_facts, timing)
        total = sum(e - s for s, e in windows.values()) if windows else scene.get("duration", 0)
        print(f"{sid}: {len(regions)} regions, cue 总时长 {total:.1f}s")

    return plan
