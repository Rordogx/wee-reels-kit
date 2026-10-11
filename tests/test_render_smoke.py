import subprocess
from pathlib import Path

from PIL import Image

from wee_reels.audio import SR, synth_music, write_wav
from wee_reels.render import render_reel
from wee_reels.spec import load_spec
from wee_reels.timeline import build_timeline


def test_bpm_is_detected_from_a_file_when_omitted(tmp_path: Path):
    write_wav(tmp_path / "bed.wav", synth_music(6.0, 100, SR, mood="drive", seed=4), SR)
    spec_path = tmp_path / "reel.yaml"
    spec_path.write_text(
        """
id: detected
client:
  name: Detector
music:
  file: bed.wav
scenes:
  - type: hook
    duration: 2
    headline: Hello
""",
        encoding="utf-8",
    )
    timeline, _samples = build_timeline(load_spec(spec_path))
    assert timeline.bpm_source == "detected"
    assert abs(timeline.bpm - 100) <= 2
    assert timeline.slots[0].scene.type == "intro"
    # The cut out of the intro sits on the detected grid.
    beat = 60.0 / timeline.bpm
    edge = timeline.slots[0].end
    offset = (edge - timeline.phase) / beat
    assert abs(offset - round(offset)) < 1e-6


def test_render_writes_a_square_master(tmp_path: Path):
    Image.new("RGB", (32, 48), (90, 70, 60)).save(tmp_path / "before.png")
    Image.new("RGB", (32, 48), (40, 70, 90)).save(tmp_path / "after.png")
    spec_path = tmp_path / "reel.yaml"
    spec_path.write_text(
        """
id: smoke
fps: 12
client:
  name: Smoke Test
  trade: Roofing
music:
  bpm: 120
  mood: calm
voiceover:
  synth: false
captions:
  timing: line
sfx:
  whoosh: true
  tick: false
  riser: false
formats: ["1:1"]
scenes:
  - type: intro
    duration: 1
  - type: hook
    duration: 1
    tag: Test
    headline: Hello
  - type: before_after
    duration: 1
    before: before.png
    after: after.png
  - type: end
    duration: 1
    cta: Go
script:
  - Hello there
""",
        encoding="utf-8",
    )
    rendered = render_reel(load_spec(spec_path), tmp_path / "out")
    assert len(rendered) == 1
    path = rendered[0].path
    assert path.is_file() and path.stat().st_size > 10_000
    assert rendered[0].true_peak <= -1.4
    probe = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "stream=codec_type,width,height,sample_rate",
            "-of",
            "csv=p=0",
            str(path),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    text = probe.stdout
    assert "1080,1080" in text
    assert "video" in text and "audio" in text
    assert "48000" in text
