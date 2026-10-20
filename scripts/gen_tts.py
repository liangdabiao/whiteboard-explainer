"""gen_tts.py — 按场景配音，生成独立 WAV 音轨、清单与 timeline。

使用共享 G3、内容缓存和本地媒体验证。输入支持 JSON 和 YAML：
  lang: zh                    # 可选：en 时默认 voice 切 en-US-JennyNeural（英文教学）
  voice: zh-CN-XiaoyiNeural   # 可覆盖；英文用 en-US-JennyNeural
  speed: 1.0
  scenes:
    - id: s01
      text: "盛唐长安，万邦来朝……"

运行目录位于 --out-dir/runs/ 下；--out-dir/timeline.json 保留兼容入口。
--dry-run / --preflight 不调用合成；--preview 须先在对话中获用户授权。
"""
from __future__ import annotations
import argparse
import asyncio
import json
from pathlib import Path

from narration_production import preview_sentence, produce_scenes
from production import load_spec, print_design, print_inspection


def load_narration(path: Path) -> dict:
    return load_spec(path)


def main():
    parser = argparse.ArgumentParser(
        description="故事手绘风视频旁白配音（edge-tts 免费）+ 生成 timeline.json",
    )
    parser.add_argument("narration_yaml", help="narration.yaml 路径")
    parser.add_argument(
        "--out-dir", default="public/audio/narration",
        help="输出目录（默认 public/audio/narration/）",
    )
    parser.add_argument("--dry-run", action="store_true", help="只打印不生成")
    parser.add_argument("--preflight", action="store_true", help="仅执行本地预检")
    parser.add_argument("--design-only", action="store_true")
    parser.add_argument("--preview", action="store_true",
                        help="单句试听，须先在对话中获用户授权，不代替 G3")
    args = parser.parse_args()

    source = Path(args.narration_yaml).resolve()
    if args.design_only or args.dry_run or args.preflight:
        spec = load_spec(source)
        if args.design_only:
            print_design(spec)
        else:
            print_inspection(spec, source.parent, "scene", runtime=args.preflight)
        return
    produce = preview_sentence if args.preview else produce_scenes
    summary = asyncio.run(produce(source, output=Path(args.out_dir)))
    print(json.dumps(summary, ensure_ascii=True))


if __name__ == "__main__":
    main()
