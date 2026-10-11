"""Paint frames and mux a loudness-normalised mix."""

from __future__ import annotations

import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

from wee_reels.audio import (
    SR,
    fit_length,
    loudness_normalize,
    mix,
    read_audio,
    synth_music,
    synth_riser,
    synth_tick,
    synth_voice,
    synth_whoosh,
    write_wav,
)
from wee_reels.easing import ease_back, ease_io, ease_out, prog
from wee_reels.formats import FORMATS
from wee_reels.layout import CaptionPlan, Compiled, FormatPlan, MarkCue, PillCue, ScenePlan, TickCue, compile_reel
from wee_reels.media import Library
from wee_reels.spec import ReelSpec, iter_jobs
from wee_reels.style import bg_frame, card_shadow, composite, draw_rule, laser_wipe, make_bg, place
from wee_reels.textfit import Block
from wee_reels.timeline import Timeline, tick_times, wipe_window


@dataclass
class Rendered:
    path: Path
    lufs: float
    true_peak: float
    duration: float
    bpm: float
    bpm_source: str
    variant: str
    format_id: str


def render_reel(
    spec: ReelSpec,
    out_dir: Path,
    formats: list[str] | None = None,
    fps: int | None = None,
) -> list[Rendered]:
    fps = fps or spec.fps
    chosen = formats or list(spec.formats)
    compiled = compile_reel(spec, chosen)
    frame_count = max(1, int(round(compiled.timeline.duration * fps)))
    audio_duration = frame_count / fps
    samples, lufs, true_peak = build_mix(spec, compiled.timeline, compiled.music, audio_duration)
    rendered: list[Rendered] = []
    with tempfile.TemporaryDirectory(prefix="wee-reels-mix-") as tmp:
        wav_path = Path(tmp) / "mix.wav"
        write_wav(wav_path, samples, SR)
        for fmt_id in chosen:
            dest = out_dir / spec.id / spec.variant_id / f"{spec.id}_{FORMATS[fmt_id].slug}.mp4"
            painter = Painter(compiled, fmt_id)
            _encode(painter, fps, frame_count, wav_path, dest)
            rendered.append(
                Rendered(
                    path=dest,
                    lufs=lufs,
                    true_peak=true_peak,
                    duration=audio_duration,
                    bpm=compiled.timeline.bpm,
                    bpm_source=compiled.timeline.bpm_source,
                    variant=spec.variant_id,
                    format_id=fmt_id,
                )
            )
    return rendered


def render_batch(
    spec: ReelSpec,
    out_dir: Path,
    formats: list[str] | None = None,
    fps: int | None = None,
) -> list[Rendered]:
    rendered: list[Rendered] = []
    for _name, job in iter_jobs(spec):
        rendered.extend(render_reel(job, out_dir, formats, fps))
    return rendered


def build_mix(
    spec: ReelSpec,
    timeline: Timeline,
    music_samples: np.ndarray | None,
    duration: float,
) -> tuple[np.ndarray, float, float]:
    n = int(round(duration * SR))
    if spec.music.file:
        source = music_samples if music_samples is not None else read_audio(spec.resolve(spec.music.file))[0]
        music = fit_length(source, n, SR)
    else:
        music = synth_music(duration, timeline.bpm, SR, spec.music.mood, spec.seed)
    voice = _voice(spec, timeline, n, duration)
    events: list[tuple[float, np.ndarray]] = []
    if spec.sfx.whoosh:
        whoosh = synth_whoosh(SR) * 0.5
        for slot in timeline.slots:
            if slot.scene.type == "before_after":
                at, _dur = wipe_window(slot.duration)
                events.append((slot.start + at - 0.03, whoosh))
    if spec.sfx.tick:
        tick = synth_tick(SR) * 0.7
        for slot in timeline.slots:
            if slot.scene.type == "checklist":
                for moment in tick_times(slot):
                    events.append((moment, tick))
    if spec.sfx.riser:
        riser = synth_riser(SR) * 0.36
        for slot in timeline.slots:
            if slot.scene.type in ("end", "outro"):
                events.append((max(0.0, slot.start - len(riser) / SR), riser))
    mixed = mix(music, voice, events, SR, timeline.beat, duration)
    return loudness_normalize(mixed, SR, spec.audio.lufs, spec.audio.true_peak)


def _voice(spec: ReelSpec, timeline: Timeline, n: int, duration: float) -> np.ndarray | None:
    if spec.voiceover.file:
        samples, _sr = read_audio(spec.resolve(spec.voiceover.file))
        if len(samples) >= n:
            return samples[:n]
        padded = np.zeros((n, 2), np.float32)
        padded[: len(samples)] = samples
        return padded
    if spec.voiceover.synth and timeline.captions:
        cues = [(cue.start, cue.end) for cue in timeline.captions]
        return synth_voice(cues, duration, SR, spec.seed)
    return None


class Painter:
    def __init__(self, compiled: Compiled, fmt_id: str) -> None:
        self.spec = compiled.spec
        self.timeline = compiled.timeline
        self.plan: FormatPlan = compiled.plans[fmt_id]
        self.fmt = self.plan.fmt
        self.colours = compiled.spec.client.colours
        self.bg = make_bg(self.fmt, self.colours.charcoal, compiled.spec.seed)
        self.library = Library()
        self._shadows: dict[tuple[int, int], Image.Image] = {}

    def frame(self, t: float) -> Image.Image:
        fr = bg_frame(self.bg, t, self.colours.glow[:3], self.fmt.glow_x, self.fmt.glow_y)
        plan = self._scene_at(t)
        local = t - plan.slot.start
        if plan.wipe is not None:
            self._paint_wipe(fr, plan, local)
        elif plan.plate:
            self._paint_plate(fr, plan, local)
        for cue in plan.texts:
            _draw_block(fr, cue.block, t, cue.start, cue.stagger, cue.dur, cue.dist, cue.out)
        for rule in plan.rules:
            draw_rule(fr, rule.x, rule.y, rule.w, t, rule.start, self.colours.gold)
        for tick in plan.ticks:
            self._paint_tick(fr, tick, t)
        for mark in plan.marks:
            self._paint_mark(fr, mark, t)
        for pill in plan.pills:
            self._paint_pill(fr, pill, t)
        if plan.slot.scene.type not in ("intro", "end", "outro"):
            for caption in self.plan.captions:
                self._paint_caption(fr, caption, t)
        return fr

    def _scene_at(self, t: float) -> ScenePlan:
        for plan in self.plan.scenes:
            if t < plan.slot.end - 1e-4:
                return plan
        return self.plan.scenes[-1]

    def _paint_wipe(self, fr: Image.Image, plan: ScenePlan, local: float) -> None:
        assert plan.wipe is not None
        wipe = plan.wipe
        well = wipe.well
        progress = local / max(0.001, plan.slot.duration)
        before = self.library.plate(
            self.spec.resolve(wipe.before), well, wipe.top_scrim, wipe.bottom_scrim
        ).frame(progress, 1.0)
        after = self.library.plate(
            self.spec.resolve(wipe.after), well, wipe.top_scrim, wipe.bottom_scrim
        ).frame(progress, -1.0)
        p = prog(local, wipe.wipe_at, wipe.wipe_dur)
        if p <= 0:
            plate = before
        elif p >= 1:
            plate = after
        else:
            plate = laser_wipe(before, after, p, self.spec.seed + 5, self.colours.glow[:3])
        if well.x > 0:
            shadow = self._shadow(well.w, well.h)
            composite(fr, shadow, well.x - 70, well.y - 52)
        composite(fr, plate, well.x, well.y)
        if well.x > 0:
            ImageDraw.Draw(fr).rectangle(
                [well.x, well.y, well.right - 1, well.bottom - 1],
                outline=(*self.colours.gold[:3], 120),
                width=2,
            )
        fade = ease_out(prog(local, 0.04, 0.22))
        before_alpha = fade * (1 - ease_io(prog(p, 0.32, 0.28)))
        after_alpha = fade * ease_io(prog(p, 0.42, 0.34))
        _blit(fr, wipe.before_label, before_alpha)
        _blit(fr, wipe.after_label, after_alpha)

    def _paint_plate(self, fr: Image.Image, plan: ScenePlan, local: float) -> None:
        well = self.fmt.well
        progress = local / max(0.001, plan.slot.duration)
        plate = self.library.plate(self.spec.resolve(plan.plate), well, True, False).frame(progress, 1.0)
        composite(fr, plate, well.x, well.y)
        dim = Image.new("RGBA", (well.w, well.h), (*self.colours.charcoal[:3], 148))
        composite(fr, dim, well.x, well.y)

    def _paint_tick(self, fr: Image.Image, tick: TickCue, t: float) -> None:
        p = prog(t, tick.start, 0.42)
        if p <= 0:
            return
        scale = 0.7 + 0.3 * ease_back(min(1.0, p * 1.2))
        radius = max(4, int(tick.size * scale / 2))
        pad = 10
        sprite = Image.new("RGBA", (radius * 2 + pad * 2, radius * 2 + pad * 2), (0, 0, 0, 0))
        draw = ImageDraw.Draw(sprite)
        gold = self.colours.gold
        width = max(3, tick.size // 11)
        draw.ellipse([pad, pad, pad + radius * 2, pad + radius * 2], outline=gold, width=width)
        if p > 0.3:
            k = ease_out((p - 0.3) / 0.7)
            cx, cy = pad + radius, pad + radius
            x0, y0 = cx - radius * 0.36, cy + radius * 0.02
            x1, y1 = cx - radius * 0.06, cy + radius * 0.32
            x2, y2 = cx + radius * 0.4, cy - radius * 0.34
            if k < 0.45:
                u = k / 0.45
                draw.line([(x0, y0), (x0 + (x1 - x0) * u, y0 + (y1 - y0) * u)], fill=gold, width=width)
            else:
                u = (k - 0.45) / 0.55
                draw.line([(x0, y0), (x1, y1)], fill=gold, width=width)
                draw.line([(x1, y1), (x1 + (x2 - x1) * u, y1 + (y2 - y1) * u)], fill=gold, width=width)
        _fade_sprite(sprite, min(1.0, p * 2.2))
        composite(fr, sprite, tick.x - radius - pad, tick.y - radius - pad)

    def _paint_mark(self, fr: Image.Image, mark: MarkCue, t: float) -> None:
        p = prog(t, mark.start, 0.5)
        if p <= 0:
            return
        scale = 0.64 + 0.36 * ease_back(p)
        if abs(scale - 1) < 0.015:
            sprite = mark.image
        else:
            sprite = mark.image.resize(
                (max(1, int(mark.image.width * scale)), max(1, int(mark.image.height * scale))),
                Image.Resampling.BILINEAR,
            )
        if p < 1:
            sprite = sprite.copy()
            _fade_sprite(sprite, min(1.0, p * 2.2))
        composite(fr, sprite, mark.cx - sprite.width / 2, mark.cy - sprite.height / 2)

    def _paint_pill(self, fr: Image.Image, pill: PillCue, t: float) -> None:
        p = prog(t, pill.start, 0.48)
        if p <= 0:
            return
        scale = 0.6 + 0.4 * ease_back(p)
        sprite = pill.image.resize(
            (max(1, int(pill.image.width * scale)), max(1, int(pill.image.height * scale))),
            Image.Resampling.BILINEAR,
        )
        if p < 1:
            _fade_sprite(sprite, min(1.0, p * 2.4))
        composite(fr, sprite, pill.cx - sprite.width / 2, pill.cy - sprite.height / 2)

    def _paint_caption(self, fr: Image.Image, caption: CaptionPlan, t: float) -> None:
        if t < caption.start or t >= caption.end:
            return
        p = ease_out(prog(t, caption.start, 0.18))
        alpha = p * (1 - ease_io(prog(t, caption.end - 0.16, 0.16)))
        if alpha <= 0.004:
            return
        block = caption.block
        dy = (1 - p) * caption.dist
        pill_w = block.widest + caption.pad_x * 2
        pill_h = block.h + caption.pad_y * 2
        left = block.x - pill_w / 2
        top = block.y + dy - caption.pad_y
        sprite = Image.new("RGBA", (int(pill_w) + 4, int(pill_h) + 4), (0, 0, 0, 0))
        ImageDraw.Draw(sprite).rounded_rectangle(
            [1, 1, pill_w, pill_h],
            radius=min(22, int(pill_h / 2)),
            fill=(10, 10, 12, int(214 * alpha)),
            outline=(*self.colours.gold[:3], int(100 * alpha)),
            width=2,
        )
        composite(fr, sprite, left, top)
        for index, glyph in enumerate(block.sprites):
            place(fr, glyph, block.x, block.y + dy + index * block.lh, alpha, block.anchor)

    def _shadow(self, width: int, height: int) -> Image.Image:
        key = (width, height)
        if key not in self._shadows:
            self._shadows[key] = card_shadow(width, height)
        return self._shadows[key]


def _draw_block(
    frame: Image.Image,
    block: Block,
    t: float,
    start: float,
    stagger: float,
    dur: float,
    dist: int,
    out: float | None,
) -> None:
    for index, sprite in enumerate(block.sprites):
        p = ease_out(prog(t, start + index * stagger, dur))
        alpha = p
        if out is not None:
            alpha *= 1 - ease_io(prog(t, out, 0.26))
        if alpha <= 0.004:
            continue
        y = block.y + index * block.lh + (1 - p) * dist
        place(frame, sprite, block.x, y, alpha, block.anchor)


def _blit(frame: Image.Image, block: Block, alpha: float) -> None:
    if alpha <= 0.004:
        return
    for index, sprite in enumerate(block.sprites):
        place(frame, sprite, block.x, block.y + index * block.lh, alpha, block.anchor)


def _fade_sprite(sprite: Image.Image, alpha: float) -> None:
    if alpha >= 0.999:
        return
    band = np.asarray(sprite.getchannel("A"), np.float32) * alpha
    sprite.putalpha(Image.fromarray(band.astype(np.uint8), "L"))


def _encode(painter: Painter, fps: int, frame_count: int, wav_path: Path, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    partial = dest.with_suffix(".part.mp4")
    w, h = painter.fmt.w, painter.fmt.h
    cmd = [
        "ffmpeg",
        "-y",
        "-hide_banner",
        "-loglevel",
        "error",
        "-f",
        "rawvideo",
        "-pix_fmt",
        "rgba",
        "-s",
        f"{w}x{h}",
        "-r",
        str(fps),
        "-i",
        "pipe:0",
        "-i",
        str(wav_path),
        "-map",
        "0:v:0",
        "-map",
        "1:a:0",
        "-c:v",
        "libx264",
        "-pix_fmt",
        "yuv420p",
        "-crf",
        "18",
        "-preset",
        "veryfast",
        "-profile:v",
        "high",
        "-c:a",
        "aac",
        "-b:a",
        "192k",
        "-ar",
        "48000",
        "-shortest",
        "-movflags",
        "+faststart",
        str(partial),
    ]
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stderr=subprocess.PIPE)
    assert proc.stdin is not None and proc.stderr is not None
    try:
        for index in range(frame_count):
            frame = painter.frame(index / fps)
            if frame.mode != "RGBA" or frame.size != (w, h):
                frame = frame.convert("RGBA")
            proc.stdin.write(frame.tobytes())
            if index % fps == 0:
                print(f"  {dest.name}  {index}/{frame_count}", file=sys.stderr)
    except BrokenPipeError:
        err = proc.stderr.read().decode()[-2000:]
        proc.wait()
        partial.unlink(missing_ok=True)
        raise RuntimeError(f"ffmpeg closed early while encoding {dest.name}:\n{err}") from None
    else:
        proc.stdin.close()
        err = proc.stderr.read().decode()
        code = proc.wait()
        if code != 0:
            partial.unlink(missing_ok=True)
            raise RuntimeError(f"ffmpeg failed on {dest.name}:\n{err[-2000:]}")
    partial.replace(dest)


def report(compiled: Compiled, verbose: bool = False) -> str:
    timeline = compiled.timeline
    lines = [
        f"{compiled.spec.id}  {compiled.spec.variant_id}  "
        f"{timeline.bpm:.1f} bpm ({timeline.bpm_source})  {timeline.duration:.2f}s"
    ]
    for slot in timeline.slots:
        lines.append(f"  {slot.start:5.2f}–{slot.end:5.2f}  {slot.scene.type}")
    for cue in timeline.captions:
        lines.append(f"  caption {cue.start:5.2f}–{cue.end:5.2f}  {cue.text}")
    lines.append("  text-fit  " + ", ".join(compiled.plans) + " ok")
    if verbose:
        for plan in compiled.plans.values():
            lines.extend(f"  {note}" for note in plan.notes)
    return "\n".join(lines)
