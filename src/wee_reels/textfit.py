"""Safe-area text fit. Overflow raises; nothing is silently clipped."""

from __future__ import annotations

from dataclasses import dataclass

from PIL import Image, ImageDraw, ImageFilter, ImageFont


class TextFitError(Exception):
    """Type cannot live inside the safe area. The message names the block and the pixels."""


@dataclass(frozen=True)
class Limit:
    """A box type is not allowed to leave. `label` is printed in the error."""

    left: int
    right: int
    top: int
    bottom: int
    label: str

    @property
    def width(self) -> int:
        return self.right - self.left

    @property
    def height(self) -> int:
        return self.bottom - self.top


def text_width(text: str, font: ImageFont.ImageFont, tracking: float = 0) -> float:
    draw = ImageDraw.Draw(Image.new("L", (1, 1)))
    if not text:
        return 0.0
    if tracking <= 0:
        return float(draw.textlength(text, font=font))
    width = 0.0
    for index, char in enumerate(text):
        width += float(draw.textlength(char, font=font))
        if index != len(text) - 1:
            width += tracking
    return width


def wrap(
    text: str,
    font: ImageFont.ImageFont,
    maxw: float,
    tracking: float = 0,
    balance: bool = True,
    name: str = "text",
    where: str = "safe",
) -> list[str]:
    """Wrap on spaces. Explicit newlines are hard breaks. A line wider than maxw raises."""
    if "\n" in text:
        lines: list[str] = []
        for part in text.split("\n"):
            lines.extend(wrap(part, font, maxw, tracking, balance, name, where))
        return lines

    def width(sample: str) -> float:
        return text_width(sample, font, tracking)

    words = text.split(" ")
    lines = []
    current = ""
    for word in words:
        if word == "":
            continue
        candidate = f"{current} {word}".strip()
        if width(candidate) <= maxw or not current:
            current = candidate
        else:
            lines.append(current)
            current = word
    if current:
        lines.append(current)
    if not lines and text.strip() == "":
        return []

    if balance and len(lines) > 1:
        lo = maxw
        while lo > 200:
            try:
                trial = wrap(text, font, lo - 10, tracking, balance=False, name=name, where=where)
            except TextFitError:
                break
            if len(trial) > len(lines):
                break
            lo -= 10
            lines = trial

    for line in lines:
        measured = width(line)
        if measured > maxw + 0.5:
            raise TextFitError(
                f"text does not fit [{where}] {name}: OVERFLOW \"{line}\" is {measured:.0f}px "
                f"wide, safe width is {maxw:.0f}px"
            )
    return lines


def _draw_tracked(
    draw: ImageDraw.ImageDraw,
    text: str,
    xy: tuple[float, float],
    font: ImageFont.ImageFont,
    fill: tuple[int, int, int, int],
    tracking: float,
) -> None:
    x, y = xy
    if tracking <= 0:
        draw.text((x, y), text, font=font, fill=fill)
        return
    for char in text:
        draw.text((x, y), char, font=font, fill=fill)
        x += float(draw.textlength(char, font=font)) + tracking


def text_sprite(
    text: str,
    font: ImageFont.ImageFont,
    fill: tuple[int, int, int, int],
    tracking: float = 0,
    shadow: tuple[tuple[int, int, int, int], int, tuple[int, int]] | None = ((0, 0, 0, 170), 8, (0, 3)),
) -> Image.Image:
    """RGBA sprite. `info` records the glyph box so placement can ignore the shadow pad."""
    tw = text_width(text, font, tracking)
    ascent, descent = font.getmetrics()
    th = ascent + descent
    pad = 28 if shadow else 4
    image = Image.new("RGBA", (int(tw + pad * 2 + 2), int(th + pad * 2 + 2)), (0, 0, 0, 0))
    if shadow:
        colour, blur, (sx, sy) = shadow
        mask = Image.new("L", image.size, 0)
        _draw_tracked(ImageDraw.Draw(mask), text, (pad + sx, pad + sy), font, 255, tracking)  # type: ignore[arg-type]
        mask = mask.filter(ImageFilter.GaussianBlur(blur))
        shade = Image.new("RGBA", image.size, colour)
        shade.putalpha(mask)
        image.alpha_composite(shade)
    _draw_tracked(ImageDraw.Draw(image), text, (pad, pad), font, fill, tracking)
    image.info["tw"] = tw
    image.info["th"] = th
    image.info["pad"] = pad
    return image


class Block:
    """A wrapped text block whose resting box, including its rise-in, must sit inside `limit`."""

    def __init__(
        self,
        text: str,
        font: ImageFont.ImageFont,
        fill: tuple[int, int, int, int],
        x: float,
        y: float,
        maxw: float,
        limit: Limit,
        anchor: str = "l",
        tracking: float = 0,
        name: str = "text",
        rise: float = 0,
        line_gap: float = 1.02,
    ) -> None:
        self.lines = wrap(text, font, maxw, tracking, name=name, where=limit.label)
        ascent, descent = font.getmetrics()
        self.lh = max(1, int((ascent + descent) * line_gap))
        self.sprites = [
            text_sprite(line, font, fill, tracking=tracking) for line in self.lines
        ]
        self.line_widths = [float(sprite.info["tw"]) for sprite in self.sprites]
        self.x = x
        self.y = y
        self.anchor = anchor
        self.h = self.lh * len(self.lines)
        self.bottom = y + self.h
        self.name = name
        self.maxw = maxw
        widest = max(self.line_widths) if self.line_widths else 0.0
        for sprite, line in zip(self.sprites, self.lines):
            tw = float(sprite.info["tw"])
            left = x - tw / 2 if anchor == "c" else x
            if left < limit.left - 1 or left + tw > limit.right + 1:
                raise TextFitError(
                    f"text does not fit [{limit.label}] {name}: \"{line}\" runs "
                    f"{left:.0f}–{left + tw:.0f}px, safe x is {limit.left}–{limit.right}px"
                )
        travel = self.bottom + rise
        if y < limit.top - 1 or travel > limit.bottom + 1:
            raise TextFitError(
                f"text does not fit [{limit.label}] {name}: block occupies {y:.0f}–{travel:.0f}px "
                f"including its rise, safe y is {limit.top}–{limit.bottom}px "
                f"({len(self.lines)} lines, widest {widest:.0f}px: {self.lines!r})"
            )

    @property
    def widest(self) -> float:
        return max(self.line_widths) if self.line_widths else 0.0
