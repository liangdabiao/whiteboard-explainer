#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""make_text_layer.py — 用 PIL 确定性渲染中文文字层

铁律：白板图上的文字一律本机字体渲染，绝不让生图模型写字（会乱码）。
渲染好的文字会被白板引擎用 CRAFT 检测出来，按笔画一笔一笔"写"出来。

用法：
  # 单条快速模式
  python scripts/make_text_layer.py base.png --out board.png \
      --title "日全食是怎么发生的" --title-size 64

  # 多块精细模式（推荐）
  python scripts/make_text_layer.py base.png --out board.png --texts texts.json

texts.json 结构（坐标是像素，原点左上）：
  [
    {"text": "太阳", "x": 200, "y": 420, "size": 40,
     "color": "#171714", "anchor": "mm", "max_width": 400, "font": "bold"}
  ]

anchor 取值（同 Pillow anchor）：lt 左上 / mm 居中 / mt 上中 / rs 右中 …
font 取值：regular(微软雅黑) / bold(雅黑粗) / handwriting(马善政毛笔) / 字体绝对路径
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from user_gates import require

from PIL import Image, ImageDraw, ImageFont

# skill 自带字体目录（毛笔体等差异化字体必须内置）
BUNDLED_FONTS = Path(__file__).resolve().parent.parent / "assets" / "fonts"
DEFAULT_COLOR = "#171714"

# 各平台系统中文字体候选（找不到就走下一个）
SYSTEM_FONT_CANDIDATES: dict[str, list[str]] = {
    "regular": [
        # Linux（思源/文泉驿）
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/wqy-zenhei/wqy-zenhei.ttc",
        # macOS（苹方/冬青黑）
        "/System/Library/Fonts/PingFang.ttc",
        "/System/Library/Fonts/STHeiti Light.ttc",
        "/System/Library/Fonts/STHeiti Medium.ttc",
        "/Library/Fonts/Songti.ttc",
        # Windows（微软雅黑）
        "C:/Windows/Fonts/msyh.ttc",
        "C:/Windows/Fonts/msyh.ttf",
        "C:/Windows/Fonts/simhei.ttf",
    ],
    "bold": [
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc",
        "/usr/share/fonts/truetype/noto/NotoSansCJK-Bold.ttc",
        "/System/Library/Fonts/PingFang.ttc",
        "C:/Windows/Fonts/msyhbd.ttc",
        "C:/Windows/Fonts/msyh.ttc",
    ],
    "kai": [
        "C:/Windows/Fonts/simkai.ttf",
    ],
    "hei": [
        "C:/Windows/Fonts/simhei.ttf",
        "/System/Library/Fonts/STHeiti Medium.ttc",
        "/usr/share/fonts/truetype/wqy/wqy-microhei.ttc",
    ],
}


def resolve_font_path(name: str) -> Path | None:
    """解析一个 preset 名（regular / bold / kai / hei / handwriting）到一个存在的字体路径。

    找不到时返回 None — 调用方决定是 warning 还是 hard error。
    """
    if name == "handwriting":
        # 毛笔字必须 skill 自带（差异化设计）
        candidate = BUNDLED_FONTS / "MaShanZheng-Regular.ttf"
        return candidate if candidate.exists() else None
    for cand in SYSTEM_FONT_CANDIDATES.get(name, []):
        if Path(cand).exists():
            return Path(cand)
    return None


def load_font(spec: str | None, size: int) -> ImageFont.FreeTypeFont:
    name = (spec or "regular").strip()
    # 绝对路径 / 文件名带后缀 → 当文件路径用
    p = Path(name)
    if p.is_absolute() or p.suffix.lower() in {".ttf", ".ttc", ".otf"}:
        if not p.exists():
            raise RuntimeError(f"--font 指定的字体不存在：{p}")
        return ImageFont.truetype(str(p), size)
    resolved = resolve_font_path(name)
    if resolved is not None:
        return ImageFont.truetype(str(resolved), size)
    # hard error：告诉用户装哪个字体，别静默失败
    if name == "handwriting":
        raise RuntimeError(
            f"字体 'handwriting' 缺失：skill 自带 {BUNDLED_FONTS / 'MaShanZheng-Regular.ttf'} "
            f"未找到。请检查 skill 是否完整解压。"
        )
    raise RuntimeError(
        f"字体 '{name}' 在本机系统字体目录里都没找到。请安装中文黑体（如 Noto Sans CJK / 微软雅黑 / 苹方）"
        f"或通过 --font /path/to/font.ttf 显式指定。"
    )


def wrap(text: str, font: ImageFont.FreeTypeFont, max_width: int | None) -> list[str]:
    if not max_width:
        return text.split("\n")
    lines: list[str] = []
    for paragraph in text.split("\n"):
        if not paragraph:
            lines.append("")
            continue
        current = ""
        for ch in paragraph:
            trial = current + ch
            if font.getlength(trial) > max_width and current:
                lines.append(current)
                current = ch
            else:
                current = trial
        lines.append(current)
    return lines


def draw_block(draw: ImageDraw.ImageDraw, block: dict) -> None:
    text = block.get("text", "")
    if not text:
        return
    font = load_font(block.get("font"), int(block.get("size", 48)))
    color = block.get("color", DEFAULT_COLOR)
    anchor = block.get("anchor", "lt")
    x, y = int(block.get("x", 0)), int(block.get("y", 0))
    lines = wrap(text, font, block.get("max_width"))
    line_gap = float(block.get("line_gap", 1.25))
    metrics = font.getmetrics()
    line_height = int((metrics[0] + metrics[1]) * line_gap)

    if "m" in anchor:
        # 多行块需要自行计算整体高度做垂直居中
        total = line_height * len(lines)
        top = y - total // 2
    elif "b" in anchor or "d" in anchor:
        top = y - line_height * len(lines)
    else:
        top = y

    for i, line in enumerate(lines):
        if not line:
            continue
        draw.text((x, top + i * line_height), line, font=font, fill=color, anchor=anchor)


def main() -> int:
    ap = argparse.ArgumentParser(description="PIL 确定性中文文字层")
    ap.add_argument("base", help="底图路径；或 'blank:WxH' 创建空白画布")
    ap.add_argument("--out", required=True, help="输出图路径")
    ap.add_argument("--texts", help="文字块 JSON 文件路径")
    ap.add_argument("--title", help="快捷：顶部标题")
    ap.add_argument("--title-size", type=int, default=64, help="标题字号（默认 64）")
    ap.add_argument("--title-y", type=int, default=40, help="标题 y（默认 40）")
    ap.add_argument("--project-root", type=Path, default=Path.cwd(),
                    help="审批所在的集目录（默认当前目录）")
    args = ap.parse_args()

    require(args.project_root, "G2")
    if args.base.startswith("blank:"):
        w, h = (int(v) for v in args.base.split(":", 1)[1].lower().split("x"))
        image = Image.new("RGB", (w, h), "white")
    else:
        image = Image.open(args.base).convert("RGB")

    blocks: list[dict] = []
    if args.texts:
        blocks = json.loads(Path(args.texts).read_text(encoding="utf-8"))
    if args.title:
        blocks.insert(0, {
            "text": args.title,
            "x": image.width // 2, "y": args.title_y + args.title_size // 2,
            "size": args.title_size, "anchor": "mm", "font": "bold",
        })

    draw = ImageDraw.Draw(image)
    for block in blocks:
        draw_block(draw, block)

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    image.save(out)
    print(f"写出 {out}（{len(blocks)} 个文字块）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
