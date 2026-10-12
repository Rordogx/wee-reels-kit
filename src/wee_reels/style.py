"""Charcoal field, grain, vignette, grid, drifting glow, gold rules, beam wipe."""

from __future__ import annotations

import math
from functools import lru_cache

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

from wee_reels.easing import ease_io, prog
from wee_reels.formats import Format
from wee_reels.textfit import text_width


def make_bg(fmt: Format, charcoal: tuple[int, int, int, int], seed: int) -> Image.Image:
    """Dark field: a vertical lift, grain, a vignette, and a faint workshop grid."""
    w, h = fmt.w, fmt.h
    rng = np.random.default_rng(seed)
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
    colour = np.array(charcoal[:3], np.float32)
    lift = (1 - yy / h)[..., None] * np.array([10, 9, 9], np.float32)
    base = colour + lift
    base += rng.normal(0, 3.2, (h, w)).astype(np.float32)[..., None]
    radius = np.sqrt(((xx - w / 2) / max(w, h)) ** 2 + ((yy - h * 0.45) / max(w, h)) ** 2)
    base *= (1 - 0.55 * np.clip(radius - 0.15, 0, 1))[..., None]
    image = Image.fromarray(np.clip(base, 0, 255).astype(np.uint8)).convert("RGBA")
    grid = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(grid)
    for x in range(fmt.safe_l, w, 90):
        draw.line([(x, 0), (x, h)], fill=(255, 255, 255, 7))
    image.alpha_composite(grid)
    return image


@lru_cache(maxsize=8)
def glow_sprite(size: int = 900, colour: tuple[int, int, int] = (232, 150, 40), strength: float = 0.22) -> Image.Image:
    yy, xx = np.mgrid[0:size, 0:size].astype(np.float32)
    radius = np.sqrt((xx - size / 2) ** 2 + (yy - size / 2) ** 2) / (size / 2)
    alpha = np.clip(1 - radius, 0, 1) ** 2.2 * 255 * strength
    arr = np.zeros((size, size, 4), np.uint8)
    arr[..., 0] = colour[0]
    arr[..., 1] = colour[1]
    arr[..., 2] = colour[2]
    arr[..., 3] = alpha.astype(np.uint8)
    return Image.fromarray(arr, "RGBA")


def composite(frame: Image.Image, sprite: Image.Image, x: float, y: float) -> None:
    """Alpha-composite, clipping sprites that hang off the frame."""
    left, top = int(x), int(y)
    if left >= frame.width or top >= frame.height or left + sprite.width <= 0 or top + sprite.height <= 0:
        return
    src = sprite
    if left < 0 or top < 0 or left + sprite.width > frame.width or top + sprite.height > frame.height:
        crop_l = max(0, -left)
        crop_t = max(0, -top)
        crop_r = min(sprite.width, frame.width - left)
        crop_b = min(sprite.height, frame.height - top)
        src = sprite.crop((crop_l, crop_t, crop_r, crop_b))
        left, top = max(0, left), max(0, top)
    if src.width <= 0 or src.height <= 0:
        return
    frame.alpha_composite(src, (left, top))


def bg_frame(bg: Image.Image, t: float, glow: tuple[int, int, int], gx: float, gy: float) -> Image.Image:
    frame = bg.copy()
    sprite = glow_sprite(colour=glow)
    cx = frame.width * gx + 120 * math.sin(t * 0.35)
    cy = frame.height * gy + 160 * math.cos(t * 0.27)
    composite(frame, sprite, cx - sprite.width / 2, cy - sprite.height / 2)
    return frame


def place(frame: Image.Image, sprite: Image.Image, x: float, y: float, alpha: float, anchor: str) -> None:
    if alpha <= 0.004:
        return
    pad = int(sprite.info["pad"])
    tw = float(sprite.info["tw"])
    left = x - tw / 2 - pad if anchor == "c" else x - pad
    top = y - pad
    image = sprite
    if alpha < 0.999:
        image = sprite.copy()
        band = np.asarray(image.getchannel("A"), np.float32) * alpha
        image.putalpha(Image.fromarray(band.astype(np.uint8), "L"))
    composite(frame, image, left, top)


def draw_rule(
    frame: Image.Image,
    x: float,
    y: float,
    width: float,
    t: float,
    start: float,
    colour: tuple[int, int, int, int],
    dur: float = 0.48,
    thickness: int = 4,
) -> None:
    p = 1 - (1 - max(0.0, min(1.0, prog(t, start, dur)))) ** 3
    if p <= 0:
        return
    ImageDraw.Draw(frame).rectangle(
        [x, y, x + max(1, int(width * p)), y + thickness],
        fill=colour,
    )


def gold_pill(
    text: str,
    font: ImageFont.ImageFont,
    gold: tuple[int, int, int, int],
    ink: tuple[int, int, int, int],
    pad_x: int = 40,
    height: int = 96,
) -> Image.Image:
    tw = text_width(text, font)
    width = int(tw + 2 * pad_x)
    image = Image.new("RGBA", (width + 48, height + 48), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle([24, 24, 24 + width, 24 + height], radius=height // 2, fill=gold)
    bbox = font.getbbox(text)
    text_h = bbox[3] - bbox[1]
    draw.text(
        (24 + pad_x, 24 + (height - text_h) / 2 - bbox[1]),
        text,
        font=font,
        fill=ink,
    )
    image.info["tw"] = width
    image.info["th"] = height
    image.info["pad"] = 24
    return image


@lru_cache(maxsize=8)
def beam_sprite(
    height: int,
    glow: tuple[int, int, int] = (255, 190, 70),
    width: int = 220,
) -> Image.Image:
    xs = np.arange(width) - width / 2
    glow_a = np.exp(-((xs / (width * 0.18)) ** 2)) * 0.75
    core_a = np.exp(-((xs / 2.6) ** 2))
    core = np.array([255, 252, 240], np.float32)
    warm = np.array(glow, np.float32)
    column = warm[None, :] * (1 - core_a[:, None]) + core[None, :] * core_a[:, None]
    arr = np.zeros((height, width, 4), np.float32)
    arr[..., :3] = column[None, :, :]
    arr[..., 3] = np.clip(glow_a + core_a, 0, 1)[None, :] * 255
    return Image.fromarray(arr.astype(np.uint8), "RGBA")


def sparks(
    draw: ImageDraw.ImageDraw,
    t: float,
    emit,
    t0: float,
    t1: float,
    seed: int = 3,
    rate: int = 70,
    spread: tuple[float, float] = (math.pi * 0.6, math.pi * 1.4),
    speed: tuple[float, float] = (300, 900),
    life: tuple[float, float] = (0.12, 0.3),
    gravity: float = 2200,
) -> None:
    rng = np.random.default_rng(seed)
    count = int((t1 - t0) * rate)
    if count <= 0:
        return
    params = rng.random((count, 4))
    for index in range(count):
        born = t0 + index / rate
        age = t - born
        span = life[0] + params[index, 2] * (life[1] - life[0])
        if age < 0 or age > span:
            continue
        x0, y0 = emit(born)
        angle = spread[0] + params[index, 0] * (spread[1] - spread[0])
        velocity = speed[0] + params[index, 1] * (speed[1] - speed[0])
        vx, vy = math.cos(angle) * velocity, math.sin(angle) * velocity

        def point(at: float, x0: float = x0, y0: float = y0, vx: float = vx, vy: float = vy) -> tuple[float, float]:
            return x0 + vx * at, y0 + vy * at + 0.5 * gravity * at * at

        k = age / span
        colour = (255, int(245 - 120 * k), int(200 - 180 * k), int(255 * (1 - k) ** 0.7))
        draw.line([point(max(0, age - 0.022)), point(age)], fill=colour, width=3 if params[index, 3] > 0.7 else 2)


def laser_wipe(prev: Image.Image, nxt: Image.Image, p: float, seed: int, glow: tuple[int, int, int]) -> Image.Image:
    """A vertical beam sweeps left to right. Left of the beam is the next picture."""
    w, h = prev.size
    beam = beam_sprite(h, glow)
    x = int(-40 + ease_io(p) * (w + 80))
    out = prev.copy()
    if x > 0:
        out.paste(nxt.crop((0, 0, min(x, w), h)), (0, 0))
    if -beam.width < x < w + beam.width:
        composite(out, beam, x - beam.width // 2, 0)
    layer = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(layer)
    span = 0.55
    for index, frac in enumerate((0.22, 0.42, 0.62, 0.8)):
        yy = int(h * frac)
        sparks(
            draw,
            p * span,
            lambda tb, yy=yy, w=w, span=span: (int(-40 + ease_io(min(1.0, tb / span)) * (w + 80)), yy),
            0,
            span,
            seed=seed + index,
            rate=48,
        )
    out.alpha_composite(layer)
    return out


def card_shadow(well_w: int, well_h: int) -> Image.Image:
    pad = 70
    image = Image.new("RGBA", (well_w + pad * 2, well_h + pad * 2), (0, 0, 0, 0))
    ImageDraw.Draw(image).rectangle([pad, pad + 18, pad + well_w, pad + 18 + well_h], fill=(0, 0, 0, 170))
    return image.filter(ImageFilter.GaussianBlur(28))
