"""Still and clip plates. The well's aspect decides the crop, per format."""

from __future__ import annotations

import subprocess
from pathlib import Path

import numpy as np
from PIL import Image

from wee_reels.formats import Rect

IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp"}
CLIP_SUFFIXES = {".mp4", ".mov", ".webm", ".m4v", ".mkv"}


def cover_window(src_w: int, src_h: int, dst_w: int, dst_h: int) -> tuple[float, float, float, float]:
    """Source rectangle, centred, that fills a destination well."""
    scale = max(dst_w / src_w, dst_h / src_h)
    win_w = dst_w / scale
    win_h = dst_h / scale
    return (src_w - win_w) / 2, (src_h - win_h) / 2, win_w, win_h


def _cover_resize(image: Image.Image, width: int, height: int) -> Image.Image:
    scale = max(width / image.width, height / image.height)
    resized = image.resize(
        (max(width, round(image.width * scale)), max(height, round(image.height * scale))),
        Image.Resampling.LANCZOS,
    )
    left = (resized.width - width) // 2
    top = (resized.height - height) // 2
    return resized.crop((left, top, left + width, top + height))


def _grade(image: Image.Image, top_scrim: bool, bottom_scrim: bool) -> Image.Image:
    """Vignette, and scrims where type sits on the picture."""
    arr = np.asarray(image.convert("RGBA")).astype(np.float32)
    h, w = arr.shape[:2]
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
    radius = np.sqrt(((xx - w / 2) / w) ** 2 + ((yy - h / 2) / h) ** 2)
    arr[..., :3] *= (1 - 0.48 * np.clip((radius - 0.28) / 0.72, 0, 1))[..., None]
    if top_scrim:
        depth = max(1, int(h * 0.30))
        ramp = np.linspace(0.62, 0, depth, dtype=np.float32)
        arr[:depth, :, :3] *= (1 - ramp)[:, None, None]
    if bottom_scrim:
        depth = max(1, int(h * 0.28))
        ramp = np.linspace(0, 0.55, depth, dtype=np.float32)
        arr[-depth:, :, :3] *= (1 - ramp)[:, None, None]
    arr[..., 3] = 255
    return Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8), "RGBA")


class PlateSource:
    """A still or a short clip, graded for one well."""

    def __init__(self, path: Path, well: Rect, top_scrim: bool, bottom_scrim: bool, zoom: float = 1.06) -> None:
        self.path = path
        self.well = well
        self.zoom = zoom
        self._frames: list[Image.Image] | None = None
        graded_w = max(well.w + 2, int(round(well.w * zoom)))
        graded_h = max(well.h + 2, int(round(well.h * zoom)))
        if path.suffix.lower() in IMAGE_SUFFIXES:
            with Image.open(path) as raw:
                covered = _cover_resize(raw.convert("RGB"), graded_w, graded_h)
            self._master = _grade(covered, top_scrim, bottom_scrim)
        elif path.suffix.lower() in CLIP_SUFFIXES:
            self._master = None
            self._frames = _decode_clip(path, graded_w, graded_h, top_scrim, bottom_scrim)
        else:
            raise ValueError(f"unsupported media {path.name}")

    def frame(self, progress: float, direction: float = 1.0) -> Image.Image:
        progress = min(1.0, max(0.0, progress))
        if self._frames is not None:
            index = min(len(self._frames) - 1, int(progress * max(1, len(self._frames) - 1)))
            master = self._frames[index]
        else:
            assert self._master is not None
            master = self._master
        max_x = master.width - self.well.w
        max_y = master.height - self.well.h
        # A short drift, opposite directions for the two sides of a wipe.
        slide = 0.35 + 0.30 * progress * direction
        slide = min(1.0, max(0.0, slide))
        x = int(max_x * slide)
        y = int(max_y * (0.42 + 0.08 * progress))
        return master.crop((x, y, x + self.well.w, y + self.well.h))


def _decode_clip(path: Path, width: int, height: int, top_scrim: bool, bottom_scrim: bool) -> list[Image.Image]:
    cmd = [
        "ffmpeg",
        "-hide_banner",
        "-loglevel",
        "error",
        "-i",
        str(path),
        "-vf",
        f"fps=24,scale={width}:{height}:force_original_aspect_ratio=increase,crop={width}:{height}",
        "-frames:v",
        "240",
        "-f",
        "rawvideo",
        "-pix_fmt",
        "rgb24",
        "-",
    ]
    proc = subprocess.run(cmd, capture_output=True)
    if proc.returncode != 0:
        tail = proc.stderr.decode()[-1200:]
        raise RuntimeError(f"could not read clip {path.name}:\n{tail}")
    frame_bytes = width * height * 3
    if not proc.stdout or len(proc.stdout) < frame_bytes:
        raise RuntimeError(f"clip {path.name} produced no frames")
    frames = []
    for offset in range(0, len(proc.stdout) - frame_bytes + 1, frame_bytes):
        raw = np.frombuffer(proc.stdout, dtype=np.uint8, count=frame_bytes, offset=offset).reshape(height, width, 3)
        frames.append(_grade(Image.fromarray(raw.copy(), "RGB"), top_scrim, bottom_scrim))
    return frames


class Library:
    def __init__(self) -> None:
        self._cache: dict[tuple, PlateSource] = {}

    def plate(self, path: Path, well: Rect, top_scrim: bool, bottom_scrim: bool) -> PlateSource:
        key = (str(path), well, top_scrim, bottom_scrim)
        if key not in self._cache:
            self._cache[key] = PlateSource(path, well, top_scrim, bottom_scrim)
        return self._cache[key]
