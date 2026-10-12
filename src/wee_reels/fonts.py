"""Oswald headlines and Inter body, vendored under the SIL Open Font License."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from PIL import ImageFont

FONT_DIR = Path(__file__).resolve().parent / "fonts"
OSWALD = FONT_DIR / "Oswald-Variable.ttf"
INTER = {
    400: FONT_DIR / "Inter-Regular.ttf",
    500: FONT_DIR / "Inter-Medium.ttf",
    600: FONT_DIR / "Inter-SemiBold.ttf",
    700: FONT_DIR / "Inter-Bold.ttf",
}


def _nearest_inter(weight: int) -> Path:
    return INTER[min(INTER, key=lambda item: abs(item - weight))]


@lru_cache(maxsize=64)
def oswald(size: int, weight: int = 640) -> ImageFont.FreeTypeFont:
    if not OSWALD.is_file():
        raise FileNotFoundError(f"Oswald is missing at {OSWALD}")
    font = ImageFont.truetype(str(OSWALD), size)
    font.set_variation_by_axes([max(200, min(700, weight))])
    return font


@lru_cache(maxsize=64)
def inter(size: int, weight: int = 500) -> ImageFont.FreeTypeFont:
    path = _nearest_inter(weight)
    if not path.is_file():
        raise FileNotFoundError(f"Inter is missing at {path}")
    return ImageFont.truetype(str(path), size)
