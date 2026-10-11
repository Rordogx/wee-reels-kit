"""Timing curves used by the type and the beam wipe."""

from __future__ import annotations


def clamp(value: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return lo if value < lo else hi if value > hi else value


def prog(t: float, start: float, dur: float) -> float:
    """Progress of an event that begins at `start` and lasts `dur` seconds."""
    if dur <= 0:
        return 1.0 if t >= start else 0.0
    return clamp((t - start) / dur)


def ease_out(t: float) -> float:
    t = clamp(t)
    return 1 - (1 - t) ** 3


def ease_io(t: float) -> float:
    t = clamp(t)
    return t * t * (3 - 2 * t)


def ease_back(t: float, s: float = 1.4) -> float:
    t = clamp(t)
    t -= 1
    return t * t * ((s + 1) * t + s) + 1
