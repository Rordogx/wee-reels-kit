import subprocess
from pathlib import Path

from PIL import Image

from wee_reels.formats import FORMATS
from wee_reels.media import PlateSource, cover_window


def test_cover_windows_differ_by_format():
    src = (1200, 1680)
    tall = cover_window(*src, FORMATS["9:16"].well.w, FORMATS["9:16"].well.h)
    feed = cover_window(*src, FORMATS["4:5"].well.w, FORMATS["4:5"].well.h)
    square = cover_window(*src, FORMATS["1:1"].well.w, FORMATS["1:1"].well.h)
    assert tall[3] > feed[3] > square[3]
    assert abs(tall[0] - square[0]) > 1 or abs(tall[1] - square[1]) > 1


def test_clip_decodes_into_the_well(tmp_path: Path):
    clip = tmp_path / "clip.mp4"
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-hide_banner",
            "-loglevel",
            "error",
            "-f",
            "lavfi",
            "-i",
            "testsrc=size=160x90:rate=12:duration=0.4",
            "-pix_fmt",
            "yuv420p",
            str(clip),
        ],
        check=True,
    )
    still = tmp_path / "still.png"
    Image.new("RGB", (120, 80), (180, 40, 40)).save(still)
    from wee_reels.formats import Rect

    well = Rect(0, 0, 64, 96)
    clip_frame = PlateSource(clip, well, top_scrim=False, bottom_scrim=False).frame(0.5)
    still_frame = PlateSource(still, well, top_scrim=True, bottom_scrim=False).frame(0.2)
    assert clip_frame.size == (well.w, well.h)
    assert still_frame.size == (well.w, well.h)
    assert clip_frame.mode == "RGBA"
