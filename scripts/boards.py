"""Board image preparation shared by rendering and assignment checks."""
from __future__ import annotations

from pathlib import Path

from PIL import Image

from production import normalize_canvas


def board_canvas(path: Path) -> list[int]:
    with Image.open(path) as image:
        width, height = image.size
    scale = min(1.0, 1280 / max(width, height))
    return [max(2, int(width * scale) // 2 * 2), max(2, int(height * scale) // 2 * 2)]


def board_image(path: Path, canvas: list[int] | None = None):
    with Image.open(path) as image:
        rgba = image.convert("RGBA")
        flat = Image.alpha_composite(Image.new("RGBA", rgba.size, "white"), rgba).convert("RGB")
    if canvas is not None:
        normalize_canvas(canvas)
        flat = flat.resize((canvas[0], canvas[1]), Image.Resampling.LANCZOS)
    return flat
