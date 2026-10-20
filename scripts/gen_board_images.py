#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""gen_board_images.py — 用 Agnes 生成白板风底图（无字）

铁律：生图模型只画"无字插画"，任何文字/标签都由 make_text_layer.py 后续叠加。
Agnes 当前免费（$0/张），但仍要遵守 skip 已存在资产的纪律。

用法：
  python scripts/gen_board_images.py boards.json --out-dir boards
  python scripts/gen_board_images.py boards.json --out-dir boards --dry-run
  python scripts/gen_board_images.py boards.json --out-dir boards --only s03 --force

boards.json:
  {
    "idea": "解释日全食",
    "scenes": [
      {"id": "s01", "visual": "a large yellow sun disc on the left, a small blue earth on the right, ..."}
    ]
  }
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from user_gates import require

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "lib"))
from lib_agnes import generate_image  # noqa: E402

from PIL import Image  # noqa: E402

# 白板风风格头：白底 + 记号笔粗轮廓 + 少量平涂马克笔色 + 禁止文字
STYLE_HEADER = (
    "whiteboard marker drawing on a pure white background, "
    "thick confident black marker outlines, hand-drawn whiteboard sketch style, "
    "a few flat marker colors only (sunflower yellow, cobalt blue, brick red, sage green), "
    "clean simple composition with generous white space, "
    "flat illustration, no shading, no gradient, no paper texture, no photograph"
)
# 运动/构图尾：白板图解式，元素之间留白，便于分区绘制
LAYOUT_FOOTER = (
    "diagram-style layout with clearly separated elements, "
    "bold simplified shapes, centered subject, wide margins"
)
NEGATIVE = (
    "text, letters, words, captions, labels, numbers, Chinese characters, "
    "watermark, logo, signature, border frame, photorealistic, 3D render, "
    "gradient background, colored background, black background, paper texture, glossy, neon"
)


def build_prompt(visual: str) -> str:
    return f"{STYLE_HEADER}\n\n{visual.strip()}\n\n{LAYOUT_FOOTER}\n\n{NEGATIVE}"


def normalize(src: Path, dst: Path, width: int, height: int) -> None:
    """缩放到目标画布并强制白底（透明/灰底贴图会破坏 ink-on-white 假设）。"""
    with Image.open(src) as im:
        rgba = im.convert("RGBA")
        bg = Image.new("RGBA", rgba.size, "white")
        flat = Image.alpha_composite(bg, rgba).convert("RGB")
        flat = flat.resize((width, height), Image.LANCZOS)
        flat.save(dst)


def gen_one(scene: dict, out_dir: Path, width: int, height: int, ratio: str,
            size: str, force: bool) -> tuple[str, str]:
    sid = scene["id"]
    dst = out_dir / f"{sid}.png"
    if dst.exists() and not force:
        return sid, "skip"
    prompt = build_prompt(scene["visual"])
    raw = out_dir / f".{sid}_raw.png"
    last = None
    for attempt in range(3):                     # Agnes 偶发失败 → 最多重试 3 次
        try:
            generate_image(prompt, raw, size=size, ratio=ratio)
            normalize(raw, dst, width, height)
            break
        except Exception as exc:
            last = exc
            print(f"  {sid}: 第 {attempt+1} 次失败（{exc}），重试…", flush=True)
            time.sleep(3)
    else:
        raise SystemExit(f"生图失败：{sid}（{last}）")
    # 白底占比校验（<60% 说明底色/深色块污染，重出一次）
    with Image.open(dst).convert("L") as im:
        px = list(im.getdata())
    white = sum(1 for v in px if v > 235) / len(px)
    if white < 0.60:
        print(f"  {sid}: 白底占比 {white:.0%} 偏低，重出一次", flush=True)
        generate_image(prompt, raw, size=size, ratio=ratio)
        normalize(raw, dst, width, height)
    try:
        raw.unlink()
    except OSError:
        pass
    return sid, f"{dst.stat().st_size // 1024}KB"


def main() -> int:
    ap = argparse.ArgumentParser(description="Agnes 白板风底图生成")
    ap.add_argument("boards", help="boards.json")
    ap.add_argument("--out-dir", default="boards")
    ap.add_argument("--width", type=int, default=1280)
    ap.add_argument("--height", type=int, default=720)
    ap.add_argument("--ratio", default="16:9", help="传给 agnes 的画幅比例（默认 16:9）")
    ap.add_argument("--size", default="2K", help="1K/2K/3K/4K（默认 2K）")
    ap.add_argument("--concurrency", type=int, default=3, help="并发数（默认 3）")
    ap.add_argument("--only", help="只生成这一拍")
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    spec = json.loads(Path(args.boards).read_text(encoding="utf-8"))
    scenes = spec["scenes"]
    if args.only:
        scenes = [s for s in scenes if s["id"] == args.only]
        if not scenes:
            sys.exit(f"--only {args.only} 无匹配")

    if args.dry_run:
        for s in scenes:
            print(f"=== {s['id']} ===\n{build_prompt(s['visual'])}\n")
        return 0

    require(Path(args.boards).resolve().parent, "G2")
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    print(f"生成 {len(scenes)} 张白板图 -> {out_dir} ({args.width}x{args.height}, {args.ratio})")
    t0 = time.monotonic()
    with ThreadPoolExecutor(max_workers=args.concurrency) as pool:
        futures = {
            pool.submit(gen_one, s, out_dir, args.width, args.height,
                        args.ratio, args.size, args.force): s["id"]
            for s in scenes
        }
        for future in as_completed(futures):
            sid = futures[future]
            try:
                _id, status = future.result()
                print(f"  {_id}: {status}", flush=True)
            except Exception as exc:  # noqa: BLE001
                print(f"  {sid}: 失败 -> {exc}", flush=True)
                raise SystemExit(f"生图失败：{sid}") from exc
    print(f"完成，用时 {time.monotonic() - t0:.0f}s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
