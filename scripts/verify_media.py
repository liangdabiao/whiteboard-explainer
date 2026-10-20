#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""verify_media.py — 产物校验层：每个音视频产物生成后必须过这道检查

纪律（probe-first / verify-after）：
  - 使用本地 ffprobe 元数据与 ffmpeg 完整解码，不依赖同级 skill
  - 每个产物必须：存在、可解码、时长与期望一致（±容差）
  - 任何一项失败 → 汇总报告并以非零码退出（禁止静默继续）

用法：
  python verify_media.py --manifest manifest.json
  python verify_media.py --file a.mp3 --expect 24.0
manifest.json: [{"path": "...", "expect": 秒数}]   expect 可省略（只查可解码）
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

from artifacts import file_digest
from media import verify
from narration_runs import read_run
from render_contract import validate_evidence

TOL = 0.75  # 时长容差（秒）。mp3 分片重编码/关键帧裁剪有固有偏差


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--manifest")
    ap.add_argument("--file")
    ap.add_argument("--expect", type=float, default=None)
    ap.add_argument("--kind", choices=["audio", "video"])
    ap.add_argument("--metadata-only", action="store_true",
                    help="仅探测元数据；不代表完整解码通过")
    ap.add_argument("--python", default=sys.executable,
                    help="兼容旧调用；本地校验不再需要另一个解释器")
    args = ap.parse_args()

    items = []
    if args.manifest:
        manifest = Path(args.manifest).resolve()
        content = json.loads(manifest.read_text(encoding="utf-8"))
        if isinstance(content, dict):
            if content.get("stage") in ("sample", "render"):
                if args.metadata_only or args.file or args.expect is not None or args.kind:
                    raise SystemExit("Verify render receipts separately with complete decoding")
                validate_evidence(manifest, content["stage"])
                print("PASS: render receipt verified with complete decoding")
                return
            content, _ = read_run(manifest)
            content = content["media"]
        for item in content:
            items.append({**item, "path": str(manifest.parent / item["path"])})
    if args.file:
        items.append({"path": args.file, "expect": args.expect})
    if not items:
        raise SystemExit("没有待校验的产物")

    rows, failed = [], 0
    for it in items:
        path = Path(it["path"])
        expect = it.get("expect")
        if not path.exists():
            rows.append((str(path), "FAIL", "文件不存在"))
            failed += 1
            continue
        try:
            if expect is not None and (not math.isfinite(float(expect)) or float(expect) <= 0):
                raise ValueError("Expected duration must be positive and finite")
            if it.get("sha256") and file_digest(path) != it["sha256"]:
                raise ValueError("Media fingerprint no longer matches the run manifest")
            result = verify(path, kind=args.kind or it.get("kind"), decode=not args.metadata_only)
            got = result["duration"]
        except Exception as exc:
            rows.append((str(path), "FAIL", f"校验失败: {exc}"))
            failed += 1
            continue
        if expect is not None and abs(got - float(expect)) > TOL:
            rows.append((str(path), "FAIL", f"时长 {got:.2f}s ≠ 期望 {expect:.2f}s"))
            failed += 1
            continue
        rows.append((str(path), "PASS", f"{got:.2f}s metadata=PASS decode={result['decode']}"))

    for filename, st, msg in rows:
        print(f"  [{st}] {filename}  {msg}")
    print(f"verify_media：{len(rows) - failed}/{len(rows)} 通过")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
