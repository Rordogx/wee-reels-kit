"""Scene timing. Cuts after the open land on the music's beat."""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

from wee_reels.audio import SR, detect_bpm, detect_phase, read_audio
from wee_reels.spec import ReelSpec, Scene, SpecError


@dataclass(frozen=True)
class Slot:
    scene: Scene
    start: float
    end: float

    @property
    def duration(self) -> float:
        return self.end - self.start


@dataclass(frozen=True)
class CaptionCue:
    text: str
    start: float
    end: float


@dataclass(frozen=True)
class Timeline:
    bpm: float
    bpm_source: str
    beat: float
    phase: float
    slots: tuple[Slot, ...]
    captions: tuple[CaptionCue, ...]
    duration: float


def wipe_window(duration: float) -> tuple[float, float]:
    """Local start and length of the beam inside a before/after scene."""
    wipe_dur = min(0.72, max(0.35, duration * 0.38))
    wipe_at = max(0.18, duration * 0.28)
    if wipe_at + wipe_dur > duration - 0.12:
        wipe_at = max(0.1, duration - wipe_dur - 0.12)
    return wipe_at, wipe_dur


def tick_times(slot: Slot) -> list[float]:
    count = len(slot.scene.items)
    if count == 0:
        return []
    gap = min(0.48, max(0.28, (slot.duration - 0.75) / count))
    origin = slot.start + 0.34
    return [origin + index * gap for index in range(count)]


def align_scenes(scenes: tuple[Scene, ...] | list[Scene], beat: float, phase: float = 0.0) -> list[float]:
    """Return boundary times, starting at 0. Later cuts snap to the beat grid."""

    def nearest(moment: float) -> float:
        k = round((moment - phase) / beat)
        return phase + k * beat

    def not_before(moment: float, floor: float) -> float:
        snapped = nearest(moment)
        if snapped + 1e-6 >= floor:
            return snapped
        k = math.ceil((floor - phase) / beat - 1e-9)
        return phase + k * beat

    bounds = [0.0]
    cursor = 0.0
    for scene in scenes:
        preferred = cursor + scene.duration
        floor = cursor + max(beat, scene.duration * 0.75)
        end = not_before(preferred, floor)
        if end <= cursor + 1e-6:
            end = cursor + beat
        bounds.append(end)
        cursor = end
    return bounds


def build_timeline(spec: ReelSpec) -> tuple[Timeline, np.ndarray | None]:
    samples: np.ndarray | None = None
    if spec.music.file:
        samples, _sr = read_audio(spec.resolve(spec.music.file))
    if spec.music.bpm is not None:
        bpm = spec.music.bpm
        source = "given"
    elif samples is not None:
        bpm = detect_bpm(samples, SR)
        source = "detected"
    else:
        bpm = 96.0
        source = "default"
    phase = detect_phase(samples, SR, bpm) if samples is not None else 0.0
    beat = 60.0 / bpm
    bounds = align_scenes(spec.scenes, beat, phase)
    slots = tuple(Slot(scene, bounds[i], bounds[i + 1]) for i, scene in enumerate(spec.scenes))
    captions = assign_captions(spec, slots, beat, phase)
    duration = slots[-1].end if slots else 0.0
    return (
        Timeline(
            bpm=bpm,
            bpm_source=source,
            beat=beat,
            phase=phase,
            slots=slots,
            captions=captions,
            duration=duration,
        ),
        samples,
    )


def assign_captions(spec: ReelSpec, slots: tuple[Slot, ...], beat: float, phase: float) -> tuple[CaptionCue, ...]:
    if not spec.script or not slots:
        return ()
    video_end = slots[-1].end
    if any(line.start is not None for line in spec.script):
        cues = []
        for line in spec.script:
            assert line.start is not None and line.end is not None
            start, end = line.start, line.end
            if spec.captions.timing == "beat":
                start = _nearest(start, beat, phase)
                end = max(start + beat * 0.5, _nearest(end, beat, phase))
            cues.append(CaptionCue(line.text, start, end))
        _check_cues(cues, slots, beat)
        return tuple(cues)

    hosts = [slot for slot in slots if slot.scene.type not in ("intro", "end", "outro")] or list(slots)
    if spec.captions.timing == "line" and len(spec.script) == len(hosts):
        cues = [CaptionCue(line.text, host.start, host.end) for line, host in zip(spec.script, hosts)]
        return tuple(cues)
    if spec.captions.timing == "line":
        span_start = hosts[0].start
        span_end = hosts[-1].end
        step = (span_end - span_start) / len(spec.script)
        cues = [
            CaptionCue(line.text, span_start + index * step, span_start + (index + 1) * step)
            for index, line in enumerate(spec.script)
        ]
        return tuple(cues)

    start = _ceil(hosts[0].start, beat, phase)
    cues = []
    for line in spec.script:
        end = start + spec.captions.beats_per_line * beat
        cues.append(CaptionCue(line.text, start, end))
        start = end
    _check_cues(cues, slots, beat, limit=video_end)
    return tuple(cues)


def _check_cues(cues: list[CaptionCue], slots: tuple[Slot, ...], beat: float, limit: float | None = None) -> None:
    if not cues:
        return
    video_end = slots[-1].end
    ceiling = video_end if limit is None else limit
    if cues[-1].end > ceiling + beat * 0.08:
        raise SpecError(
            [
                f"captions run to {cues[-1].end:.2f}s, past the reel at {ceiling:.2f}s. "
                "Shorten the script, lower beats_per_line, or give the scenes more time."
            ]
        )
    hosts = [slot for slot in slots if slot.scene.type not in ("intro", "end", "outro")]
    for cue in cues:
        visible = any(cue.end > slot.start + 1e-3 and cue.start < slot.end - 1e-3 for slot in hosts)
        if not visible:
            raise SpecError(
                [
                    f"script line {cue.text!r} is timed entirely over the intro or outro, "
                    "so it would never appear"
                ]
            )


def _nearest(moment: float, beat: float, phase: float) -> float:
    k = round((moment - phase) / beat)
    return phase + k * beat


def _ceil(moment: float, beat: float, phase: float) -> float:
    k = math.ceil((moment - phase) / beat - 1e-9)
    return phase + k * beat
