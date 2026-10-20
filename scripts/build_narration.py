#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""build_narration.py — 把讲稿变成「精确 cue」的音频 + 渲染用 plan.json

核心思想（本 skill 的音画对齐方法）：
  每拍拆成若干 region，每个 region 配一句 annotation（子句）。
  逐子句 TTS 得到分片 → 中间垫静音 gap → concat 成该拍音轨。
  用分片真实时长累加出每个 region 的 [start, end] —— 帧级"讲到哪画到哪"。

用法：
  python scripts/build_narration.py plan.build.json
  python scripts/build_narration.py plan.build.json --dry-run
输出：独立运行目录内的 WAV、cue 与 manifest，以及兼容的 plan.json。
"""
from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

from narration_production import produce_regions
from production import load_spec, print_design, print_inspection


async def build(spec: dict, root: Path, dry: bool, mode: str = "standard",
                rate: str | None = None) -> dict:
    """兼容既有直接调用；审批与运行协议由配音生产 module 执行。"""
    return await produce_regions(spec, root, dry=dry, mode=mode, rate=rate)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("spec", help="plan.build.json")
    ap.add_argument("--dry-run", action="store_true", help="只打印子句，不 TTS")
    ap.add_argument("--preflight", action="store_true", help="仅检查本地输入和运行依赖")
    ap.add_argument("--design-only", action="store_true", help="G2 前只展示教学画面计划，不读取画板")
    args = ap.parse_args()

    spec_path = Path(args.spec).resolve()
    root = spec_path.parent
    if args.design_only or args.dry_run or args.preflight:
        spec = load_spec(spec_path)
    if args.design_only:
        print_design(spec)
        return 0

    if args.dry_run or args.preflight:
        print_inspection(spec, root, runtime=args.preflight)
        return 0

    asyncio.run(produce_regions(spec_path))
    return 0


if __name__ == "__main__":
    sys.exit(main())
