#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""render_explainer.py — 白板讲解动画渲染器

输入：plan.json（每拍：白板图 + 音频 + region 绘制窗口）
输出：每拍 mp4 → concat 成片

三种音画对齐档位，自动降级：
  1. 精确档  region 写了 start/end（来自 LRC/逐句 TTS 真实时间戳）→ 帧级"讲到哪画到哪"
  2. 估算档  region 只有 annotation 文本 → 按字符数 70% / 面积 30% 分配窗口
  3. 均分档  没有 regions → 引擎全局启发式，前 70% 时间画完

用法：
  python scripts/render_explainer.py plan.json --out out/eclipse.mp4
  python scripts/render_explainer.py plan.json --out out/x.mp4 --only s01 --force
  python scripts/render_explainer.py plan.json --dry-run
"""
from __future__ import annotations

import argparse
import json
import math
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

from artifacts import atomic_bytes, atomic_json, file_digest, file_lock
from boards import board_canvas, board_image
from check_assignment import audit
from media import concat_manifest
from render_contract import QUALITY, RenderReceipt, frame_duration, render_config, scene_key, snapshot, verify_video
from user_gates import GateError, require, require_render, require_teaching, require_narration

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "lib"))
import theme  # noqa: E402
from themed_render import tint_video  # noqa: E402

try:
    from whiteboard_animator import WhiteboardAnimator
except ImportError:  # pragma: no cover
    sys.exit(
        "未找到 whiteboard_animator。请先跑：\n"
        "  scripts/setup.sh        # Linux / macOS / Git Bash\n"
        "  scripts/setup.ps1       # Windows PowerShell\n"
        "或在已激活 venv 里安装：\n"
        "  pip install 'whiteboard-animator==0.1.1'\n"
    )

# 绘制预算：占音频总时长的比例，剩下的时间保留已完成画面（呼吸/收尾）
DRAW_BUDGET = 0.75
# 单个 region 窗口的最小秒数，太窄会让引擎装不下绘制量而 RuntimeError
MIN_WINDOW = 0.6
# 分配窗口时字符数 vs 面积 的权重（与引擎内置策略一致）
NARRATION_WEIGHT = 0.7


def log(msg: str) -> None:
    print(msg, flush=True)


def run(cmd: list[str]) -> subprocess.CompletedProcess:
    """Windows 中文路径安全：所有 subprocess 显式 utf-8。"""
    return subprocess.run(
        cmd, check=True, capture_output=True,
        encoding="utf-8", errors="replace",
    )


def probe_duration(path: Path) -> float:
    """读媒体时长。优先 ffprobe；本机没装 ffprobe 时退回 ffmpeg 解析。"""
    try:
        out = run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                   "-of", "csv=p=0", str(path)])
        return _check_duration(float(out.stdout.strip()), path)
    except (FileNotFoundError, subprocess.CalledProcessError):
        pass
    # 兜底：用 ffmpeg 读 stderr 里的 Duration
    theme.setup_ffmpeg_env()
    ff = theme.ffmpeg_path()
    if not ff:
        raise FileNotFoundError("需要 ffprobe 或 ffmpeg 才能读时长，两者都没找到")
    r = subprocess.run([ff, "-i", str(path)], capture_output=True, encoding="utf-8",
                       errors="replace")
    m = re.search(r"Duration:\s*(\d+):(\d+):(\d+\.?\d*)", r.stderr)
    if not m:
        raise ValueError(f"无法读取时长: {path}")
    h, mi, s = int(m.group(1)), int(m.group(2)), float(m.group(3))
    return _check_duration(h * 3600 + mi * 60 + s, path)


def _check_duration(duration: float, path: Path) -> float:
    if not math.isfinite(duration) or duration <= 0:
        raise ValueError(f"时长非法: {path} -> {duration}")
    return duration


# --------------------------------------------------------------------------
# region 窗口计算
# --------------------------------------------------------------------------

def normalize_box(region: dict) -> dict:
    """把单个 box 统一成 {ymin,xmin,ymax,xmax} 归一化 0-1000 字典。

    接受：box: {ymin,xmin,ymax,xmax} / [ymin,xmin,ymax,xmax] / box_2d。
    """
    box = region.get("box")
    if box is None:
        box = region.get("box_2d")
    if box is None:
        raise ValueError(f"region '{region.get('label')}' 缺少 box 或 box_2d")
    if isinstance(box, dict):
        keys = ("ymin", "xmin", "ymax", "xmax")
        missing = [k for k in keys if k not in box]
        if missing:
            raise ValueError(f"region '{region.get('label')}' box 缺字段: {missing}")
        return {k: int(box[k]) for k in keys}
    if isinstance(box, (list, tuple)) and len(box) == 4:
        ymin, xmin, ymax, xmax = [int(v) for v in box]
        return {"ymin": ymin, "xmin": xmin, "ymax": ymax, "xmax": xmax}
    raise ValueError(f"region '{region.get('label')}' box 格式无法识别: {box!r}")


def region_boxes(region: dict) -> list[dict]:
    """region 的 box 支持单个或数组，统一返回归一化 box 列表。"""
    box = region.get("box")
    raw = region.get("box_2d") if box is None else box
    if raw is None:
        raise ValueError(f"region '{region.get('label')}' 缺少 box 或 box_2d")
    items = raw if isinstance(raw, list) and raw and isinstance(raw[0], (dict, list, tuple)) else [raw]
    fake = {"label": region.get("label"), "box": items[0]}
    if len(items) > 1:
        return [normalize_box({"label": region.get("label"), "box": b}) for b in items]
    return [normalize_box(fake)]


def box_area(box: dict) -> int:
    return max((box["xmax"] - box["xmin"]) * (box["ymax"] - box["ymin"]), 1)


def _overlap(a: dict, b: dict) -> float:
    """两个 0-1000 归一化 box 的交叠面积（对 a 的占比）。"""
    ix = max(0, min(a["xmax"], b["xmax"]) - max(a["xmin"], b["xmin"]))
    iy = max(0, min(a["ymax"], b["ymax"]) - max(a["ymin"], b["ymin"]))
    return ix * iy / max(box_area(a), 1)


def build_windows(regions: list[dict], total: float) -> list[dict]:
    """给每个 region 算出 [start, end) 绘制窗口。

    - 有 cue（start/end，来自 build_narration 的真实时间戳）→ 精确档
    - 无 cue 且无 annotation 的纯图形 region → 并入与其空间重叠最大的
      cue 窗口，和那段讲解同时画出（图形属于那段话的一部分）
    - 全部无 cue → 按 annotation 字符数与面积加权估算窗口
    """
    cued = [r for r in regions if r.get("start") is not None and r.get("end") is not None]
    if cued:
        windows: list[dict] = []
        for r in sorted(cued, key=lambda x: float(x["start"])):
            windows.append({
                "boxes": region_boxes(r),
                "start": float(r["start"]),
                "end": float(r["end"]),
            })
        for r in regions:
            if r.get("start") is not None:
                continue
            boxes = region_boxes(r)
            best_w, best_score = None, 0.0
            for w in windows:
                for b in boxes:
                    for b2 in w["boxes"]:
                        score = _overlap(b, b2)
                        if score > best_score:
                            best_w, best_score = w, score
            (best_w or windows[-1])["boxes"].extend(boxes)
        return windows

    ordered = sorted(regions, key=lambda r: r.get("reveal_order", 10_000))
    chars = [len(str(r.get("annotation") or "").strip()) for r in ordered]
    areas = [sum(box_area(b) for b in region_boxes(r)) for r in ordered]
    total_chars, total_area = sum(chars), sum(areas)

    shares = []
    for c, a in zip(chars, areas):
        if total_chars:
            shares.append(NARRATION_WEIGHT * (c / total_chars)
                          + (1 - NARRATION_WEIGHT) * (a / total_area))
        else:
            shares.append(a / total_area)
    share_sum = sum(shares) or 1.0

    budget = DRAW_BUDGET * total
    windows, cursor = [], 0.0
    for region, share in zip(ordered, shares):
        duration = max(budget * share / share_sum, MIN_WINDOW)
        windows.append({
            "boxes": region_boxes(region),
            "start": round(cursor, 3),
            "end": round(cursor + duration, 3),
        })
        cursor += duration
    return windows


def widen(windows: list[dict], factor: float, total: float) -> list[dict]:
    """窗口整体放大（引擎装不下绘制量时的自动重试策略）。"""
    out = []
    for w in windows:
        start = w["start"] / factor
        end = min(w["end"] * factor, total * 0.97)
        out.append({"boxes": w["boxes"], "start": round(start, 3), "end": round(end, 3)})
    return out


# --------------------------------------------------------------------------
# 单拍渲染
# --------------------------------------------------------------------------

def render_scene(scene: dict, root: Path, out_dir: Path, quality: str,
                 animator: WhiteboardAnimator | None, force: bool,
                 config: dict | None = None, facts: dict | None = None) -> tuple[Path, float]:
    config = config or render_config(quality, "whiteboard", canvas=board_canvas(root / scene["image"]))
    requested = (probe_duration(root / scene["audio"]) if scene.get("audio")
                 else float(scene.get("duration", 8)))
    if scene.get("duration_override") is not None:
        requested = float(scene["duration_override"])
    expected = frame_duration(requested, config["fps"], scene)
    key = scene_key(scene, root, config)
    target = out_dir / f"{scene['id']}-{key}.mp4"
    metadata = target.with_suffix(".mp4.json")
    if not force:
        try:
            proof = json.loads(metadata.read_text(encoding="utf-8"))
            if proof["key"] == key and proof["sha256"] == file_digest(target):
                result = verify_video(target, config, bool(scene.get("audio")))
                if abs(result["duration"] - expected) > 2 / config["fps"] + 0.05:
                    raise ValueError("Cached scene duration differs from the current input")
                if facts is not None:
                    facts.update({"generated": 0, "reused": 1})
                return target, result["duration"]
        except (OSError, ValueError, KeyError, TypeError):
            pass
    out_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="render-", dir=out_dir) as td:
        result_path, _ = _render_uncached(scene, root, Path(td), config, animator)
        if scene_key(scene, root, config) != key:
            raise ValueError("Scene input changed during rendering; cache was not published")
        result = verify_video(result_path, config, bool(scene.get("audio")))
        if abs(result["duration"] - expected) > 2 / config["fps"] + 0.05:
            raise ValueError("Rendered scene duration differs from the current input")
        atomic_bytes(target, result_path.read_bytes())
        atomic_json(metadata, {"key": key, "sha256": file_digest(target)})
    if facts is not None:
        facts.update({"generated": 1, "reused": 0})
    return target, result["duration"]


def _render_uncached(scene: dict, root: Path, out_dir: Path, config: dict,
                     animator: WhiteboardAnimator | None) -> tuple[Path, float]:
    sid = scene["id"]
    scene_out = out_dir / f"{sid}.mp4"

    image_path = root / scene["image"]
    if not image_path.is_file():
        raise FileNotFoundError(f"[{sid}] 图不存在: {image_path}")

    audio_path = None
    if scene.get("audio"):
        audio_path = root / scene["audio"]
        if not audio_path.is_file():
            raise FileNotFoundError(f"[{sid}] 音频不存在: {audio_path}")

    if audio_path:
        total = probe_duration(audio_path)
    else:
        total = float(scene.get("duration") or 8.0)
    if scene.get("duration_override"):
        total = float(scene["duration_override"])
    fps, bitrate = config["fps"], config["bitrate"]
    total = frame_duration(total, fps, scene)

    img = np.array(board_image(image_path, config["canvas"]))

    regions = scene.get("regions") or []
    active = total
    if scene.get("hold", 0) or scene.get("tail_pad", 0):
        active = min(total, math.ceil(float(scene["narration_duration"]) * fps - 1e-9) / fps)
    element_plan = build_windows(regions, active) if regions else None
    need_plan = element_plan is not None
    animator = animator or WhiteboardAnimator(fade_duration=0.06 if need_plan else 0.12)
    if (animator.fade_duration == 0.12) == need_plan:
        animator = WhiteboardAnimator(fade_duration=0.06 if need_plan else 0.12)

    video_only = out_dir / f"{sid}.video_only.mp4"
    last_error = None
    for attempt in range(4):
        try:
            animator.render_to_file(
                img, active * DRAW_BUDGET, active, str(video_only),
                fps=fps, bitrate=bitrate,
                element_plan=(element_plan if attempt == 0 or not element_plan
                              else widen(element_plan, 1 + 0.15 * attempt, active)),
            )
            last_error = None
            break
        except RuntimeError as exc:
            if any(r.get("start") is not None for r in regions):
                raise RuntimeError("Exact cue rendering failed; adjust the scene instead of widening cues") from exc
            last_error = exc
            log(f"  [{sid}] 窗口过窄（{exc}），自动放宽 {int(15 * (attempt + 1))}% 重试")
    if last_error:
        raise last_error
    if total > active + 1e-6:
        last_frame = out_dir / "last.png"
        run(["ffmpeg", "-v", "error", "-nostdin", "-i", str(video_only),
             "-ss", str(max(0, active - 1 / fps - 1e-6)), "-frames:v", "1", str(last_frame)])
        hold_video = out_dir / "hold.mp4"
        run(["ffmpeg", "-v", "error", "-nostdin", "-loop", "1", "-i", str(last_frame),
             "-r", str(fps), "-frames:v", str(round((total - active) * fps)),
             "-c:v", "libx264", "-b:v", bitrate, "-pix_fmt", "yuv420p", str(hold_video)])
        held = out_dir / "held.mp4"
        concatenate([video_only, hold_video], held)
        held.replace(video_only)

    if audio_path is None:
        video_only.replace(scene_out)
    else:
        run(["ffmpeg", "-y", "-i", str(video_only), "-i", str(audio_path),
             "-c:v", "copy", "-c:a", "aac", "-ar", "24000", "-ac", "1",
             "-af", "apad", "-t", str(total), str(scene_out)])
    try:
        video_only.unlink()
    except OSError:
        pass

    # 换主题时，成片后再整体染色（引擎只认纯白，底色进不了帧缓冲）
    if config["theme"] != "whiteboard":
        tint_video(str(scene_out), config["theme"])
        log(f"  [{sid}] 已按主题 {config['theme']} 染色底色")

    total = probe_duration(scene_out)
    return scene_out, total


def concatenate(parts: list[Path], output: Path) -> None:
    if len(parts) == 1:
        if parts[0].resolve() != output.resolve():
            run(["ffmpeg", "-y", "-i", str(parts[0]), "-c", "copy", str(output)])
        return
    concat_list = concat_manifest(parts, output)
    try:
        run(["ffmpeg", "-y", "-f", "concat", "-safe", "0",
             "-i", str(concat_list), "-c", "copy", str(output)])
    finally:
        if concat_list.exists():
            concat_list.unlink()


def produce(args, receipt: RenderReceipt) -> dict:
    plan_path = Path(args.plan).resolve()
    root = plan_path.parent
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    if not args.dry_run:
        require(root, "G3" if args.only else "G4")
        require_teaching(root, plan)
    name = args.theme or os.environ.get("WHITEBOARD_THEME") or "whiteboard"
    theme.get(name)
    theme.setup_ffmpeg_env()
    theme.patch_no_tpad()
    canvas = plan.get("canvas")
    if canvas is None:
        if not plan.get("scenes"):
            raise ValueError("The render plan requires scenes")
        canvas = board_canvas(root / plan["scenes"][0]["image"])
    config = render_config(args.quality, name,
                           args.fps if args.fps is not None else plan.get("fps"), canvas)
    with receipt.check("inputs") as detail:
        context = snapshot(plan_path, plan, config)
        if not args.dry_run:
            require_narration(root, context)
        detail["method"] = "snapshot: 输入结构校验 + 素材/配置/实现指纹"
        detail["evidence"] = f"key={context['key']}, scenes={len(context['scenes'])}"
    receipt.bind(context)
    if args.dry_run:
        return {"status": "PASS", "stage": "PREFLIGHT", "context": context,
                "checks": receipt.checks, "check_evidence": receipt.check_evidence}
    if not args.only:
        require_render(root, context["key"])
    with receipt.check("assignment"):
        assignment = audit(plan, root, config["canvas"])
    receipt.assignment(assignment)
    scenes = [s for s in plan["scenes"] if not args.only or s["id"] == args.only]
    if not scenes:
        raise ValueError("--only does not match a scene")
    output = Path(args.out)
    output = output if output.is_absolute() else root / output
    if output.suffix.lower() != ".mp4":
        raise ValueError("Render output must use the .mp4 extension")
    with file_lock(output.parent / f".{output.name}.lock", "render"):
        if not args.only and output.exists() and not args.force:
            raise ValueError("Output already exists; choose another output or explicitly use --force")
        with receipt.run(root, only=args.only) as workspace:
            with receipt.check("render") as detail:
                parts = []
                for scene in scenes:
                    facts: dict = {}
                    part, _ = render_scene(scene, root, root / ".video-cache", args.quality,
                                           None, args.force, config, facts)
                    receipt.cache(facts)
                    parts.append(part)
                movie = workspace / "video.mp4"
                concatenate(parts, movie)
                detail["method"] = "whiteboard_animator 逐拍渲染 + ffmpeg concat"
                detail["evidence"] = f"scenes={len(parts)}"
            result = receipt.video(movie)
            frames = []
            if args.only:
                for index, fraction in enumerate((0.25, 0.8)):
                    frame = workspace / f"frame-{index}.png"
                    run(["ffmpeg", "-v", "error", "-nostdin", "-ss", str(result["duration"] * fraction),
                         "-i", str(movie), "-frames:v", "1", str(frame)])
                    frames.append(frame)
            return receipt.complete(frames=frames, output=None if args.only else output)

def main() -> int:
    ap = argparse.ArgumentParser(description="白板讲解动画渲染器")
    ap.add_argument("plan", help="plan.json 路径")
    ap.add_argument("--out", required=True, help="成片输出路径（.mp4）")
    ap.add_argument("--quality", choices=list(QUALITY), default="medium")
    ap.add_argument("--fps", type=int, help="覆盖帧率，须与 G4 样片一致")
    ap.add_argument("--only", help="只渲这一拍（如 s01），不 concat")
    ap.add_argument("--force", action="store_true", help="强制重渲并允许替换当前输出；历史运行副本保留")
    ap.add_argument("--dry-run", action="store_true", help="只打印计划，不渲染")
    ap.add_argument("--theme", help="配色主题（whiteboard/warm/cool/mint/sakura）；"
                                   "非默认主题会走 lib/themed_render.py 成片后整体染色")
    args = ap.parse_args()

    receipt = RenderReceipt()
    try:
        report = produce(args, receipt)
    except (Exception, GateError) as exc:
        report = receipt.failure(exc, blocked=isinstance(exc, GateError))
        print(str(exc), file=sys.stderr)
        log("REPORT " + json.dumps(report, ensure_ascii=True))
        return 1
    log("REPORT " + json.dumps(report, ensure_ascii=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
