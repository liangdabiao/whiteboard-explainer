#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""build_narration_fast.py — 带语速与静音裁剪的旁白生成（短视频默认 +22%）

复用 build_narration 的审批、缓存与运行归属。语速默认 +22%，
对加工音频裁首尾静音；原始旁白仍可跨处理配置复用。

用法：
  python scripts/build_narration_fast.py plan.build.json [--rate +22%]
  python scripts/build_narration_fast.py plan.build.json --dry-run
"""
from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

from production import load_spec, print_design, print_inspection
from narration_production import produce_regions

def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("spec", help="plan.build.json")
    ap.add_argument("--rate", help="须匹配 spec.rate（未指定时使用 spec.rate 或 +22%%）")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--preflight", action="store_true")
    ap.add_argument("--design-only", action="store_true")
    args = ap.parse_args()

    spec_path = Path(args.spec).resolve()
    root = spec_path.parent
    if args.design_only or args.dry_run or args.preflight:
        spec = load_spec(spec_path)
    if args.design_only:
        print_design(spec)
        return 0

    if args.dry_run or args.preflight:
        print_inspection(spec, root, "fast", args.rate, args.preflight)
        return 0

    asyncio.run(produce_regions(spec_path, mode="fast", rate=args.rate))
    return 0


if __name__ == "__main__":
    sys.exit(main())
