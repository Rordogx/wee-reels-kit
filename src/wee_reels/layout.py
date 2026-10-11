"""Turn a timeline into per-format draw plans. Type that does not fit raises TextFitError."""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from PIL import Image, ImageDraw, ImageFilter, ImageFont

from wee_reels.formats import FORMATS, Format, Rect
from wee_reels.fonts import inter, oswald
from wee_reels.spec import ReelSpec, SpecError
from wee_reels.style import gold_pill
from wee_reels.textfit import Block, Limit, TextFitError, text_width, wrap
from wee_reels.timeline import CaptionCue, Slot, Timeline, build_timeline, tick_times, wipe_window


@dataclass
class TextCue:
    block: Block
    start: float
    stagger: float
    dur: float
    dist: int
    out: float | None


@dataclass
class RuleCue:
    x: float
    y: float
    w: float
    start: float


@dataclass
class TickCue:
    x: float
    y: float
    start: float
    size: int


@dataclass
class MarkCue:
    image: Image.Image
    cx: float
    cy: float
    start: float
    pad: int


@dataclass
class PillCue:
    image: Image.Image
    cx: float
    cy: float
    start: float


@dataclass
class WipePlan:
    before: str
    after: str
    well: Rect
    top_scrim: bool
    bottom_scrim: bool
    wipe_at: float
    wipe_dur: float
    before_label: Block
    after_label: Block


@dataclass
class ScenePlan:
    slot: Slot
    texts: list[TextCue] = field(default_factory=list)
    rules: list[RuleCue] = field(default_factory=list)
    ticks: list[TickCue] = field(default_factory=list)
    marks: list[MarkCue] = field(default_factory=list)
    pills: list[PillCue] = field(default_factory=list)
    wipe: WipePlan | None = None
    plate: str = ""


@dataclass
class CaptionPlan:
    block: Block
    start: float
    end: float
    dist: int
    pad_x: int
    pad_y: int


@dataclass
class FormatPlan:
    fmt: Format
    scenes: list[ScenePlan]
    captions: list[CaptionPlan]
    notes: list[str]


@dataclass
class Compiled:
    spec: ReelSpec
    timeline: Timeline
    plans: dict[str, FormatPlan]
    music: object


def compile_reel(spec: ReelSpec, formats: list[str] | None = None) -> Compiled:
    timeline, music = build_timeline(spec)
    chosen = formats or list(spec.formats)
    plans = {fmt_id: plan_format(spec, timeline, FORMATS[fmt_id]) for fmt_id in chosen}
    return Compiled(spec=spec, timeline=timeline, plans=plans, music=music)


def plan_format(spec: ReelSpec, timeline: Timeline, fmt: Format) -> FormatPlan:
    notes: list[str] = []
    scenes = [plan_scene(spec, slot, fmt, notes) for slot in timeline.slots]
    captions = [
        plan_caption(cue, fmt, notes, spec.client.colours.ink) for cue in timeline.captions
    ]
    return FormatPlan(fmt=fmt, scenes=scenes, captions=captions, notes=notes)


def content_limit(fmt: Format) -> Limit:
    return Limit(fmt.safe_l, fmt.safe_r, fmt.safe_t, fmt.safe_b - fmt.caption_band, f"{fmt.id} safe")


def full_limit(fmt: Format) -> Limit:
    return Limit(fmt.safe_l, fmt.safe_r, fmt.safe_t, fmt.safe_b, f"{fmt.id} safe")


def plan_scene(spec: ReelSpec, slot: Slot, fmt: Format, notes: list[str]) -> ScenePlan:
    kind = slot.scene.type
    if kind == "intro":
        return plan_intro(spec, slot, fmt, notes)
    if kind == "hook":
        return plan_hook(spec, slot, fmt, notes)
    if kind == "before_after":
        return plan_wipe(spec, slot, fmt, notes)
    if kind == "checklist":
        return plan_checklist(spec, slot, fmt, notes)
    if kind == "title":
        return plan_title(spec, slot, fmt, notes)
    if kind in ("end", "outro"):
        return plan_end(spec, slot, fmt, notes)
    raise SpecError([f"no layout for scene type {kind}"])


def plan_hook(spec: ReelSpec, slot: Slot, fmt: Format, notes: list[str]) -> ScenePlan:
    box = content_limit(fmt)
    scene = slot.scene
    pieces: list[tuple[str, int]] = []
    tag_font = inter(fmt.tag, 650)
    head_font = oswald(fmt.headline, 640)
    sub_font = inter(fmt.body, 500)
    if scene.tag:
        pieces.append(("tag", _line_height(tag_font)))
        pieces.append(("gap", _gap(fmt, 22)))
    pieces.append(("head", _block_height(scene.headline, head_font, box.width, 0, "hook.headline", box)))
    pieces.append(("gap", _gap(fmt, 16)))
    pieces.append(("rule", 4))
    if scene.sub:
        pieces.append(("gap", _gap(fmt, 18)))
        pieces.append(("sub", _block_height(scene.sub, sub_font, box.width, 0, "hook.sub", box)))
    y = _place(fmt.valign, box, _total(pieces), fmt.rise, "hook", fmt.top_pad)
    plan = ScenePlan(slot=slot, plate=scene.plate)
    out = _out(slot)
    x = _x(fmt, fmt.anchor)
    for kind, height in pieces:
        if kind == "gap":
            y += height
        elif kind == "rule":
            width = _rule_w(fmt)
            plan.rules.append(RuleCue(_rule_x(fmt, fmt.anchor, width), y, width, slot.start + 0.28))
            y += height
        elif kind == "tag":
            plan.texts.append(_cue(scene.tag.upper(), tag_font, spec.client.colours.gold, x, y, box, fmt.anchor, fmt.tag * 0.16, "hook.tag", fmt.rise, slot.start + 0.06, out))
            y += height
        elif kind == "head":
            plan.texts.append(_cue(scene.headline, head_font, spec.client.colours.ink, x, y, box, fmt.anchor, 0, "hook.headline", fmt.rise, slot.start + 0.12, out, stagger=0.07))
            y += height
        elif kind == "sub":
            plan.texts.append(_cue(scene.sub, sub_font, spec.client.colours.muted, x, y, box, fmt.anchor, 0, "hook.sub", fmt.rise, slot.start + 0.34, out))
            y += height
    _log(notes, fmt, plan)
    return plan


def plan_title(spec: ReelSpec, slot: Slot, fmt: Format, notes: list[str]) -> ScenePlan:
    box = content_limit(fmt)
    scene = slot.scene
    anchor = fmt.anchor
    pieces: list[tuple[str, int]] = []
    tag_font = inter(fmt.tag, 650)
    head_font = oswald(fmt.title, 640)
    sub_font = inter(fmt.body, 500)
    if scene.tag:
        pieces.append(("tag", _line_height(tag_font)))
        pieces.append(("gap", _gap(fmt, 18)))
    pieces.append(("head", _block_height(scene.headline, head_font, box.width, 0, "title.headline", box)))
    pieces.append(("gap", _gap(fmt, 14)))
    pieces.append(("rule", 4))
    if scene.sub:
        pieces.append(("gap", _gap(fmt, 16)))
        pieces.append(("sub", _block_height(scene.sub, sub_font, box.width, 0, "title.sub", box)))
    y = _place("center", box, _total(pieces), fmt.rise, "title")
    plan = ScenePlan(slot=slot, plate=scene.plate)
    out = _out(slot)
    x = _x(fmt, anchor)
    colours = spec.client.colours
    for kind, height in pieces:
        if kind == "gap":
            y += height
        elif kind == "rule":
            width = _rule_w(fmt)
            plan.rules.append(RuleCue(_rule_x(fmt, anchor, width), y, width, slot.start + 0.22))
            y += height
        elif kind == "tag":
            plan.texts.append(_cue(scene.tag.upper(), tag_font, colours.gold, x, y, box, anchor, fmt.tag * 0.16, "title.tag", fmt.rise, slot.start + 0.06, out))
            y += height
        elif kind == "head":
            plan.texts.append(_cue(scene.headline, head_font, colours.ink, x, y, box, anchor, 0, "title.headline", fmt.rise, slot.start + 0.1, out, stagger=0.07))
            y += height
        else:
            plan.texts.append(_cue(scene.sub, sub_font, colours.muted, x, y, box, anchor, 0, "title.sub", fmt.rise, slot.start + 0.28, out))
            y += height
    _log(notes, fmt, plan)
    return plan


def plan_checklist(spec: ReelSpec, slot: Slot, fmt: Format, notes: list[str]) -> ScenePlan:
    box = content_limit(fmt)
    scene = slot.scene
    anchor = fmt.anchor
    colours = spec.client.colours
    tag_font = inter(fmt.tag, 650)
    title_font = oswald(fmt.title, 620)
    item_font = inter(fmt.item, 500)
    gutter = fmt.tick + 26
    text_max = box.width - gutter
    pieces: list[tuple[str, int]] = []
    if scene.tag:
        pieces.append(("tag", _line_height(tag_font)))
        pieces.append(("gap", _gap(fmt, 16)))
    if scene.title:
        pieces.append(("title", _block_height(scene.title, title_font, box.width, 0, "checklist.title", box)))
        pieces.append(("gap", _gap(fmt, 12)))
        pieces.append(("rule", 4))
        pieces.append(("gap", _gap(fmt, 18)))
    item_heights = []
    item_widths = []
    for index, item in enumerate(scene.items):
        height, widest = _block_size(item, item_font, text_max, 0, f"checklist.item{index + 1}", box)
        row = max(height, fmt.tick + 6)
        item_heights.append((height, row))
        item_widths.append(widest)
        pieces.append((f"item{index}", row))
        if index != len(scene.items) - 1:
            pieces.append(("gap", _gap(fmt, 14)))
    y = _place(fmt.valign, box, _total(pieces), fmt.rise, "checklist", fmt.top_pad)
    plan = ScenePlan(slot=slot, plate=scene.plate)
    out = _out(slot)
    x = _x(fmt, anchor)
    ticks = tick_times(slot)
    item_index = 0
    for kind, height in pieces:
        if kind == "gap":
            y += height
            continue
        if kind == "rule":
            width = _rule_w(fmt)
            plan.rules.append(RuleCue(_rule_x(fmt, anchor, width), y, width, slot.start + 0.2))
            y += height
            continue
        if kind == "tag":
            plan.texts.append(_cue(scene.tag.upper(), tag_font, colours.gold, x, y, box, anchor, fmt.tag * 0.16, "checklist.tag", fmt.rise, slot.start + 0.05, out))
            y += height
            continue
        if kind == "title":
            plan.texts.append(_cue(scene.title, title_font, colours.ink, x, y, box, anchor, 0, "checklist.title", fmt.rise, slot.start + 0.1, out, stagger=0.06))
            y += height
            continue
        text_h, row_h = item_heights[item_index]
        widest = item_widths[item_index]
        row_w = gutter + widest
        if anchor == "c":
            row_left = fmt.cx - row_w / 2
        else:
            row_left = float(fmt.safe_l)
        text_x = row_left + gutter
        text_y = y + (row_h - text_h) / 2
        plan.texts.append(
            _cue(
                scene.items[item_index],
                item_font,
                colours.ink,
                text_x,
                text_y,
                box,
                "l",
                0,
                f"checklist.item{item_index + 1}",
                fmt.rise,
                ticks[item_index] - 0.08,
                out,
                maxw=text_max,
            )
        )
        plan.ticks.append(
            TickCue(row_left + fmt.tick / 2, y + row_h / 2, ticks[item_index], fmt.tick)
        )
        y += height
        item_index += 1
    _log(notes, fmt, plan)
    return plan


def plan_wipe(spec: ReelSpec, slot: Slot, fmt: Format, notes: list[str]) -> ScenePlan:
    box = content_limit(fmt)
    scene = slot.scene
    top, bottom = _scrims(fmt)
    label_anchor = "c" if fmt.id == "1:1" else "l"
    label_x = fmt.cx if label_anchor == "c" else fmt.safe_l
    label_y = float(fmt.safe_t + (6 if fmt.id != "1:1" else 2))
    font = inter(fmt.tag, 650)
    tracking = fmt.tag * 0.18
    before = _block(
        scene.before_label.upper(),
        font,
        spec.client.colours.gold,
        label_x,
        label_y,
        box,
        label_anchor,
        tracking,
        "wipe.before",
        rise=0,
    )
    after = _block(
        scene.after_label.upper(),
        font,
        spec.client.colours.gold,
        label_x,
        label_y,
        box,
        label_anchor,
        tracking,
        "wipe.after",
        rise=0,
    )
    wipe_at, wipe_dur = wipe_window(slot.duration)
    plan = ScenePlan(
        slot=slot,
        wipe=WipePlan(
            before=scene.before,
            after=scene.after,
            well=fmt.well,
            top_scrim=top,
            bottom_scrim=bottom,
            wipe_at=wipe_at,
            wipe_dur=wipe_dur,
            before_label=before,
            after_label=after,
        ),
    )
    notes.append(f"{fmt.id} wipe.before y={before.y:.0f} {before.lines}")
    notes.append(f"{fmt.id} wipe.after y={after.y:.0f} {after.lines}")
    return plan


def plan_intro(spec: ReelSpec, slot: Slot, fmt: Format, notes: list[str]) -> ScenePlan:
    return _brand_card(spec, slot, fmt, notes, closing=False)


def plan_end(spec: ReelSpec, slot: Slot, fmt: Format, notes: list[str]) -> ScenePlan:
    return _brand_card(spec, slot, fmt, notes, closing=True)


def _brand_card(spec: ReelSpec, slot: Slot, fmt: Format, notes: list[str], closing: bool) -> ScenePlan:
    box = full_limit(fmt)
    scene = slot.scene
    colours = spec.client.colours
    anchor = "c"
    x = float(fmt.cx)
    tag_font = inter(fmt.tag, 650)
    name_font = oswald(fmt.name, 640)
    body_font = inter(max(22, fmt.body - 2), 500)
    tag = (scene.tag or spec.client.trade or ("Introducing" if not closing else "")).upper()
    cta = scene.cta or "Get in touch"
    pieces: list[tuple[str, int]] = []
    if tag:
        pieces.append(("tag", _line_height(tag_font)))
        pieces.append(("gap", _gap(fmt, 14)))
    pieces.append(("mark", fmt.mark))
    pieces.append(("gap", _gap(fmt, 16)))
    name_h = _block_height(spec.client.name, name_font, box.width, 0, "brand.name", box)
    pieces.append(("name", name_h))
    pieces.append(("gap", _gap(fmt, 14)))
    pieces.append(("rule", 4))
    if closing:
        pieces.append(("gap", _gap(fmt, 20)))
        pill_h = max(72, int(fmt.name * 0.95))
        pieces.append(("pill", pill_h))
        contact = [line for line in (scene.line, spec.client.web, spec.client.phone) if line]
        for index, _line in enumerate(contact):
            pieces.append(("gap", _gap(fmt, 10)))
            pieces.append((f"contact{index}", _block_height(_line, body_font, box.width, 0, f"brand.contact{index + 1}", box)))
    elif spec.client.tagline:
        pieces.append(("gap", _gap(fmt, 16)))
        pieces.append(("tagline", _block_height(spec.client.tagline, body_font, box.width, 0, "brand.tagline", box)))
    y = _place("center", box, _total(pieces), fmt.rise if not closing else max(8, fmt.rise // 2), "end" if closing else "intro")
    plan = ScenePlan(slot=slot)
    out = None if closing else _out(slot)
    rise = fmt.rise if not closing else max(8, fmt.rise // 2)
    contact_lines = [line for line in (scene.line, spec.client.web, spec.client.phone) if line] if closing else []
    contact_index = 0
    pill_font = oswald(max(28, int(fmt.name * 0.52)), 600)
    for kind, height in pieces:
        if kind == "gap":
            y += height
            continue
        if kind == "tag":
            plan.texts.append(_cue(tag, tag_font, colours.gold, x, y, box, anchor, fmt.tag * 0.18, "brand.tag", rise, slot.start + 0.08, out))
        elif kind == "mark":
            image, pad = _mark(spec, fmt.mark)
            plan.marks.append(MarkCue(image, x, y + fmt.mark / 2, slot.start + 0.05, pad))
        elif kind == "name":
            plan.texts.append(_cue(spec.client.name, name_font, colours.ink, x, y, box, anchor, 0, "brand.name", rise, slot.start + 0.16, out, stagger=0.06))
        elif kind == "rule":
            width = min(320, int(box.width * 0.42))
            plan.rules.append(RuleCue(x - width / 2, y, width, slot.start + 0.34))
        elif kind == "pill":
            _fit_pill(cta, pill_font, box, "brand.cta")
            image = gold_pill(cta, pill_font, colours.gold, colours.charcoal, pad_x=36, height=height)
            plan.pills.append(PillCue(image, x, y + height / 2, slot.start + 0.42))
        elif kind == "tagline":
            plan.texts.append(_cue(spec.client.tagline, body_font, colours.muted, x, y, box, anchor, 0, "brand.tagline", rise, slot.start + 0.4, out))
        elif kind.startswith("contact"):
            plan.texts.append(
                _cue(
                    contact_lines[contact_index],
                    body_font,
                    colours.muted,
                    x,
                    y,
                    box,
                    anchor,
                    0,
                    f"brand.contact{contact_index + 1}",
                    rise,
                    slot.start + 0.52 + contact_index * 0.06,
                    None,
                )
            )
            contact_index += 1
        y += height
    _log(notes, fmt, plan)
    return plan


def plan_caption(
    cue: CaptionCue,
    fmt: Format,
    notes: list[str],
    fill: tuple[int, int, int, int],
) -> CaptionPlan:
    pad_x, pad_y = 22, 12
    top = fmt.safe_b - fmt.caption_band
    limit = Limit(
        fmt.safe_l + pad_x,
        fmt.safe_r - pad_x,
        top + pad_y,
        fmt.safe_b - pad_y,
        f"{fmt.id} caption",
    )
    font = inter(fmt.caption, 600)
    dist = max(8, fmt.rise // 2)
    # Vertically centre a wrapped caption in the band, then let Block enforce the rise.
    height = _block_height(cue.text, font, limit.width, 0, "caption", limit)
    y = limit.top + max(0, (limit.height - height - dist) / 2)
    block = _block(cue.text, font, fill, fmt.cx, y, limit, "c", 0, "caption", dist)
    notes.append(f"{fmt.id} caption y={block.y:.0f}-{block.bottom:.0f} {block.lines}")
    return CaptionPlan(block=block, start=cue.start, end=cue.end, dist=dist, pad_x=pad_x, pad_y=pad_y)


def _cue(
    text: str,
    font: ImageFont.ImageFont,
    fill: tuple[int, int, int, int],
    x: float,
    y: float,
    limit: Limit,
    anchor: str,
    tracking: float,
    name: str,
    rise: float,
    start: float,
    out: float | None,
    stagger: float = 0.0,
    maxw: float | None = None,
) -> TextCue:
    block = _block(text, font, fill, x, y, limit, anchor, tracking, name, rise, maxw=maxw)
    return TextCue(block, start, stagger, 0.5, int(rise), out)


def _block(
    text: str,
    font: ImageFont.ImageFont,
    fill: tuple[int, int, int, int],
    x: float,
    y: float,
    limit: Limit,
    anchor: str,
    tracking: float,
    name: str,
    rise: float,
    maxw: float | None = None,
) -> Block:
    return Block(
        text,
        font,
        fill,
        x,
        y,
        limit.width if maxw is None else maxw,
        limit,
        anchor=anchor,
        tracking=tracking,
        name=name,
        rise=rise,
    )


def _block_height(text: str, font: ImageFont.ImageFont, maxw: float, tracking: float, name: str, limit: Limit) -> int:
    height, _widest = _block_size(text, font, maxw, tracking, name, limit)
    return height


def _block_size(
    text: str,
    font: ImageFont.ImageFont,
    maxw: float,
    tracking: float,
    name: str,
    limit: Limit,
) -> tuple[int, float]:
    lines = wrap(text, font, maxw, tracking, name=name, where=limit.label)
    if not lines:
        raise TextFitError(f"text does not fit [{limit.label}] {name}: empty text")
    ascent, descent = font.getmetrics()
    lh = max(1, int((ascent + descent) * 1.02))
    widths = [text_width(line, font, tracking) for line in lines]
    return lh * len(lines), max(widths)


def _line_height(font: ImageFont.ImageFont) -> int:
    ascent, descent = font.getmetrics()
    return max(1, int((ascent + descent) * 1.02))


def _total(pieces: list[tuple[str, int]]) -> int:
    return sum(height for _kind, height in pieces)


def _place(valign: str, box: Limit, total: int, rise: int, name: str, top_pad: int = 8) -> float:
    needed = total + rise
    if needed > box.height:
        raise TextFitError(
            f"text does not fit [{box.label}] {name}: stack is {needed:.0f}px including its rise, "
            f"safe height is {box.height}px"
        )
    if valign == "center":
        y = box.top + (box.height - needed) / 2
    else:
        y = float(box.top + top_pad)
    if y + needed > box.bottom + 1:
        raise TextFitError(
            f"text does not fit [{box.label}] {name}: stack runs {y:.0f}–{y + needed:.0f}px, "
            f"safe y is {box.top}–{box.bottom}px"
        )
    return y


def _out(slot: Slot) -> float | None:
    if slot.duration < 1.1:
        return None
    return slot.end - 0.28


def _gap(fmt: Format, base: int) -> int:
    scale = fmt.headline / 84
    return max(8, int(round(base * scale)))


def _x(fmt: Format, anchor: str) -> float:
    return float(fmt.cx if anchor == "c" else fmt.safe_l)


def _rule_w(fmt: Format) -> int:
    return int(min(260, fmt.maxw * 0.42))


def _rule_x(fmt: Format, anchor: str, width: float) -> float:
    if anchor == "c":
        return fmt.cx - width / 2
    return float(fmt.safe_l)


def _scrims(fmt: Format) -> tuple[bool, bool]:
    if fmt.id == "9:16":
        return True, True
    if fmt.id == "4:5":
        return True, False
    return False, False


def _fit_pill(text: str, font: ImageFont.ImageFont, box: Limit, name: str) -> None:
    width = text_width(text, font) + 72
    if width > box.width:
        raise TextFitError(
            f"text does not fit [{box.label}] {name}: OVERFLOW \"{text}\" pill is {width:.0f}px "
            f"wide, safe width is {box.width:.0f}px"
        )


def _mark(spec: ReelSpec, size: int) -> tuple[Image.Image, int]:
    if spec.client.logo:
        path = spec.resolve(spec.client.logo)
        try:
            with Image.open(path) as raw:
                glyph = raw.convert("RGBA")
        except OSError as exc:
            raise SpecError([f"could not read logo {path.name}: {exc}"], str(spec.source)) from exc
    else:
        glyph = _monogram(spec.client.name, size, spec.client.colours.gold)
    return _badge(glyph, size)


def _monogram(name: str, size: int, gold: tuple[int, int, int, int]) -> Image.Image:
    image = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    inset = max(3, size // 18)
    draw.ellipse([inset, inset, size - inset - 1, size - inset - 1], outline=gold, width=max(3, size // 28))
    letters = _initials(name)
    font = oswald(int(size * 0.34), 600)
    bbox = font.getbbox(letters)
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    draw.text(((size - tw) / 2 - bbox[0], (size - th) / 2 - bbox[1]), letters, font=font, fill=gold)
    return image


def _initials(name: str) -> str:
    words = [word for word in re.split(r"[\s&+/]+", name) if word]
    letters = "".join(word[0] for word in words[:2]).upper()
    return letters or "•"


def _badge(glyph: Image.Image, size: int) -> tuple[Image.Image, int]:
    fitted = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    thumb = glyph.copy()
    thumb.thumbnail((size - 6, size - 6), Image.Resampling.LANCZOS)
    fitted.alpha_composite(thumb, ((size - thumb.width) // 2, (size - thumb.height) // 2))
    pad = 28
    canvas = Image.new("RGBA", (size + pad * 2, size + pad * 2), (0, 0, 0, 0))
    shade = Image.new("RGBA", fitted.size, (0, 0, 0, 0))
    alpha = fitted.getchannel("A")
    black = Image.new("L", fitted.size, 0)
    black.paste(alpha, (0, 0))
    shade_rgba = Image.new("RGBA", fitted.size, (0, 0, 0, 160))
    shade_rgba.putalpha(black.point(lambda p: int(p * 0.7)))
    shade.alpha_composite(shade_rgba)
    shadow = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
    shadow.alpha_composite(shade, (pad, pad + 8))
    shadow = shadow.filter(ImageFilter.GaussianBlur(8))
    canvas.alpha_composite(shadow)
    canvas.alpha_composite(fitted, (pad, pad))
    return canvas, pad


def _log(notes: list[str], fmt: Format, plan: ScenePlan) -> None:
    for cue in plan.texts:
        notes.append(f"{fmt.id} {cue.block.name} y={cue.block.y:.0f}-{cue.block.bottom:.0f} {cue.block.lines}")
