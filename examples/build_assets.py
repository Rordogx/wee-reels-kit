"""Draw the fictional stills and marks shipped with the example specs.

These are placeholders, not photographs of anyone's roof or lodge.
Run from the repo root: python examples/build_assets.py
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

ROOT = Path(__file__).resolve().parents[1]

W, H = 1200, 1680


def _gradient(top: tuple[int, int, int], bottom: tuple[int, int, int], wobble: float = 0.0) -> Image.Image:
    yy = np.linspace(0, 1, H, dtype=np.float32)[:, None]
    if wobble:
        xx = np.linspace(-1, 1, W, dtype=np.float32)[None, :]
        yy = np.clip(yy + wobble * xx * 0.15, 0, 1)
    arr = np.empty((H, W, 3), np.float32)
    for channel, a, b in zip(range(3), top, bottom):
        arr[..., channel] = a + (b - a) * yy
    return Image.fromarray(arr.astype(np.uint8), "RGB")


def _save(image: Image.Image, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    image.save(path, "PNG", optimize=True)
    print(path.relative_to(ROOT))


def _house(draw: ImageDraw.ImageDraw, wall: tuple[int, int, int], left: int, right: int, top: int, bottom: int) -> None:
    draw.rectangle([left, top, right, bottom], fill=wall)
    draw.polygon([(left - 36, top + 8), ((left + right) // 2, top - 220), (right + 36, top + 8)], fill=wall)


def _roof_courses(
    base: Image.Image,
    slate: tuple[int, int, int],
    line: tuple[int, int, int],
    missing: list[tuple[int, int]] | None = None,
) -> None:
    """Tile courses across the upper roof plane. `missing` is (course, column) gaps."""
    overlay = Image.new("RGBA", base.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    apex_y, eave_y = 430, 980
    left0, right0 = 250, 950
    left1, right1 = 70, 1130
    courses = 14
    gaps = set(missing or [])
    for course in range(courses):
        t0 = course / courses
        t1 = (course + 1) / courses
        y0 = apex_y + (eave_y - apex_y) * t0
        y1 = apex_y + (eave_y - apex_y) * t1
        x0 = left0 + (left1 - left0) * t0
        x1 = right0 + (right1 - right0) * t0
        columns = 9 + course // 3
        shift = 18 if course % 2 else 0
        for column in range(columns):
            if (course, column) in gaps:
                continue
            a = (column + 0.04) / columns
            b = (column + 0.96) / columns
            draw.polygon(
                [
                    (x0 + (x1 - x0) * a + shift, y0 + 4),
                    (x0 + (x1 - x0) * b + shift, y0 + 4),
                    (x0 + (x1 - x0) * b + shift * 0.4, y1 - 3),
                    (x0 + (x1 - x0) * a + shift * 0.4, y1 - 3),
                ],
                fill=slate if (course + column) % 5 else tuple(min(255, c + 18) for c in slate),
            )
        draw.line([(x0, y0), (x1, y0)], fill=line, width=2)
    base.paste(overlay, (0, 0), overlay)


def roof(before: bool) -> Image.Image:
    if before:
        image = _gradient((92, 96, 102), (176, 170, 160))
        slate, mortar = (58, 52, 48), (28, 24, 22)
        missing = [(4, 3), (5, 3), (8, 6), (9, 6), (11, 2)]
    else:
        image = _gradient((126, 154, 176), (228, 196, 150), wobble=0.4)
        slate, mortar = (42, 49, 62), (24, 28, 34)
        missing = []
    draw = ImageDraw.Draw(image)
    # Distant ridge.
    draw.polygon([(0, 980), (180, 860), (420, 940), (700, 820), (980, 910), (1200, 860), (1200, 1680), (0, 1680)], fill=(70, 74, 70) if before else (86, 92, 78))
    draw.rectangle([0, 1180, 1200, 1680], fill=(62, 58, 52) if before else (74, 78, 64))
    _house(draw, (92, 78, 68) if before else (214, 206, 194), 160, 1040, 980, 1500)
    # Door and a window, kept low so the roof is the subject.
    draw.rectangle([560, 1240, 680, 1500], fill=(48, 36, 30))
    draw.rectangle([300, 1180, 460, 1320], fill=(36, 48, 58) if before else (232, 210, 170))
    draw.rectangle([760, 1180, 920, 1320], fill=(36, 48, 58) if before else (232, 210, 170))
    _roof_courses(image, slate, mortar, missing)
    draw = ImageDraw.Draw(image)
    # Chimney.
    draw.rectangle([860, 520, 960, 760], fill=(112, 78, 64) if before else (90, 62, 52))
    draw.rectangle([848, 500, 972, 540], fill=(70, 48, 40))
    if before:
        # A damp run under the missing courses.
        stain = Image.new("RGBA", image.size, (0, 0, 0, 0))
        sd = ImageDraw.Draw(stain)
        sd.polygon([(430, 700), (520, 690), (560, 1100), (400, 1120)], fill=(40, 48, 52, 90))
        image = Image.alpha_composite(image.convert("RGBA"), stain).convert("RGB")
    else:
        # Low warm light along the eaves.
        glow = Image.new("RGBA", image.size, (0, 0, 0, 0))
        gd = ImageDraw.Draw(glow)
        gd.polygon([(40, 980), (1160, 980), (1200, 1180), (0, 1220)], fill=(232, 178, 90, 50))
        image = Image.alpha_composite(image.convert("RGBA"), glow).convert("RGB")
    return image.filter(ImageFilter.SMOOTH)


def lodge(before: bool) -> Image.Image:
    if before:
        image = _gradient((138, 142, 136), (186, 184, 176))
        wall, roof, window, hill = (138, 132, 122), (74, 70, 64), (58, 62, 66), (108, 112, 100)
        water = (120, 124, 122)
    else:
        image = _gradient((18, 22, 32), (58, 72, 92))
        wall, roof, window, hill = (48, 44, 40), (22, 24, 28), (232, 178, 90), (28, 36, 32)
        water = (16, 28, 36)
    draw = ImageDraw.Draw(image)
    draw.polygon([(0, 760), (220, 560), (480, 700), (760, 480), (1040, 660), (1200, 560), (1200, 1680), (0, 1680)], fill=hill)
    draw.rectangle([0, 1180, 1200, 1680], fill=water)
    # Lodge body, kept in the centre so square and tall crops both keep it.
    draw.polygon([(260, 860), (600, 620), (940, 860)], fill=roof)
    draw.rectangle([320, 860, 880, 1180], fill=wall)
    draw.rectangle([560, 980, 660, 1180], fill=(32, 26, 22))
    for x in (380, 700):
        draw.rectangle([x, 940, x + 110, 1040], fill=window)
        if not before:
            bloom = Image.new("RGBA", image.size, (0, 0, 0, 0))
            bd = ImageDraw.Draw(bloom)
            bd.ellipse([x - 30, 910, x + 140, 1070], fill=(232, 170, 70, 70))
            image = Image.alpha_composite(image.convert("RGBA"), bloom).convert("RGB")
            draw = ImageDraw.Draw(image)
    if not before:
        # A simple reflection in the water.
        lodge = image.crop((300, 620, 960, 1180)).transpose(Image.Transpose.FLIP_TOP_BOTTOM)
        lodge = lodge.convert("RGBA")
        alpha = lodge.getchannel("A").point(lambda p: 70)
        lodge.putalpha(alpha)
        reflection = Image.new("RGBA", image.size, (0, 0, 0, 0))
        reflection.paste(lodge, (300, 1180), lodge)
        image = Image.alpha_composite(image.convert("RGBA"), reflection).convert("RGB")
    else:
        draw = ImageDraw.Draw(image)
        draw.rectangle([0, 1180, 1200, 1220], fill=(150, 148, 140))
    return image


def logo(kind: str) -> Image.Image:
    size = 512
    image = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    gold = (232, 178, 58, 255)
    draw.ellipse([36, 36, 476, 476], outline=gold, width=14)
    if kind == "roof":
        draw.line([(140, 300), (256, 168), (372, 300)], fill=gold, width=18)
        draw.line([(168, 300), (344, 300)], fill=gold, width=10)
    else:
        draw.line([(148, 332), (256, 156), (364, 332)], fill=gold, width=16)
        draw.line([(196, 332), (316, 332)], fill=gold, width=10)
    return image


def main() -> None:
    _save(roof(before=True), ROOT / "examples/northlane/assets/before.png")
    _save(roof(before=False), ROOT / "examples/northlane/assets/after.png")
    _save(logo("roof"), ROOT / "examples/northlane/assets/logo.png")
    _save(lodge(before=True), ROOT / "examples/mothbrae/assets/before.png")
    _save(lodge(before=False), ROOT / "examples/mothbrae/assets/after.png")
    _save(logo("lodge"), ROOT / "examples/mothbrae/assets/logo.png")


if __name__ == "__main__":
    main()
