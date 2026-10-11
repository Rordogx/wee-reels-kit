"""Per-format canvases. Each ratio is its own composition, not a crop of 9:16."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Rect:
    x: int
    y: int
    w: int
    h: int

    @property
    def right(self) -> int:
        return self.x + self.w

    @property
    def bottom(self) -> int:
        return self.y + self.h


@dataclass(frozen=True)
class Format:
    id: str
    w: int
    h: int
    safe_l: int
    safe_r: int
    safe_t: int
    safe_b: int
    anchor: str  # l or c — where editorial type sits
    valign: str  # top or center — hook and checklist
    headline: int
    title: int
    body: int
    tag: int
    caption: int
    item: int
    name: int
    tick: int
    mark: int
    caption_band: int
    rise: int
    top_pad: int
    well: Rect
    glow_x: float
    glow_y: float

    @property
    def maxw(self) -> int:
        return self.safe_r - self.safe_l

    @property
    def cx(self) -> int:
        return (self.safe_l + self.safe_r) // 2

    @property
    def slug(self) -> str:
        return self.id.replace(":", "x")


# Safe boxes keep type off the platform UI.
# 9:16 follows the book-ad vertical box (90 / 990 / 220 / 1570) with a caption band inside it.
# 4:5 keeps a charcoal caption dock under the picture. 1:1 is a centred card on the field.
FORMATS: dict[str, Format] = {
    "9:16": Format(
        id="9:16",
        w=1080,
        h=1920,
        safe_l=90,
        safe_r=990,
        safe_t=220,
        safe_b=1570,
        anchor="l",
        valign="top",
        headline=84,
        title=76,
        body=34,
        tag=26,
        caption=36,
        item=40,
        name=68,
        tick=36,
        mark=168,
        caption_band=168,
        rise=30,
        top_pad=28,
        well=Rect(0, 0, 1080, 1920),
        glow_x=0.72,
        glow_y=0.26,
    ),
    "4:5": Format(
        id="4:5",
        w=1080,
        h=1350,
        safe_l=80,
        safe_r=1000,
        safe_t=88,
        safe_b=1260,
        anchor="l",
        valign="top",
        headline=68,
        title=62,
        body=30,
        tag=24,
        caption=32,
        item=34,
        name=56,
        tick=32,
        mark=140,
        caption_band=156,
        rise=22,
        top_pad=18,
        well=Rect(0, 0, 1080, 1088),
        glow_x=0.70,
        glow_y=0.30,
    ),
    "1:1": Format(
        id="1:1",
        w=1080,
        h=1080,
        safe_l=88,
        safe_r=992,
        safe_t=64,
        safe_b=1016,
        anchor="c",
        valign="center",
        headline=56,
        title=50,
        body=26,
        tag=22,
        caption=28,
        item=28,
        name=46,
        tick=28,
        mark=112,
        caption_band=132,
        rise=16,
        top_pad=8,
        well=Rect(78, 148, 924, 708),
        glow_x=0.62,
        glow_y=0.36,
    ),
}

ALIASES = {
    "9:16": "9:16",
    "9x16": "9:16",
    "vertical": "9:16",
    "reel": "9:16",
    "4:5": "4:5",
    "4x5": "4:5",
    "feed": "4:5",
    "1:1": "1:1",
    "1x1": "1:1",
    "square": "1:1",
}


def canonical_format(name: str) -> str | None:
    return ALIASES.get(name.strip().lower())
