import json
from pathlib import Path

import pytest

from wee_reels.spec import SpecError, apply_variant, iter_jobs, load_spec

ROOT = Path(__file__).resolve().parents[1]
NORTHLANE = ROOT / "examples" / "northlane" / "reel.yaml"
MOTHBRAE = ROOT / "examples" / "mothbrae" / "reel.yaml"


def _write(tmp_path: Path, body: str, name: str = "reel.yaml") -> Path:
    path = tmp_path / name
    path.write_text(body, encoding="utf-8")
    return path


def _png(tmp_path: Path) -> None:
    from PIL import Image

    image = Image.new("RGB", (8, 8), (20, 20, 20))
    image.save(tmp_path / "a.png")
    image.save(tmp_path / "b.png")


BASE = """
id: sample
client:
  name: Sample Roofing
  trade: Roofing
scenes:
  - type: hook
    duration: 2
    headline: Hello
  - type: before_after
    duration: 2
    before: a.png
    after: b.png
  - type: checklist
    duration: 2
    items: ["One", "Two"]
"""


def test_examples_load_and_keep_branding():
    spec = load_spec(NORTHLANE)
    assert spec.id == "northlane"
    assert spec.scenes[0].type == "intro"
    assert spec.scenes[-1].type == "end"
    assert spec.formats == ("9:16", "4:5", "1:1")
    assert spec.music.bpm == 96
    assert load_spec(MOTHBRAE).captions.timing == "beat"


def test_json_spec_loads(tmp_path: Path):
    _png(tmp_path)
    raw = {
        "id": "json-reel",
        "client": {"name": "Json Roofing"},
        "scenes": [
            {"type": "hook", "duration": 1.5, "headline": "Hello from JSON"},
            {"type": "end", "duration": 1.5, "cta": "Book"},
        ],
    }
    path = tmp_path / "reel.json"
    path.write_text(json.dumps(raw), encoding="utf-8")
    spec = load_spec(path)
    assert spec.scenes[0].type == "intro"
    assert any(scene.headline == "Hello from JSON" for scene in spec.scenes)


def test_missing_name_unknown_scene_and_bad_colour(tmp_path: Path):
    path = _write(
        tmp_path,
        """
id: sample
client:
  colours:
    gold: not-a-colour
scenes:
  - type: slideshow
    duration: 1
    headline: Hi
""",
    )
    with pytest.raises(SpecError) as caught:
        load_spec(path)
    text = str(caught.value)
    assert "client.name" in text
    assert "slideshow" in text
    assert "gold" in text


def test_missing_media_and_checklist_items(tmp_path: Path):
    path = _write(
        tmp_path,
        """
id: sample
client:
  name: Sample
scenes:
  - type: before_after
    duration: 2
    before: missing.png
    after: missing.png
  - type: checklist
    duration: 2
    items: []
""",
    )
    with pytest.raises(SpecError) as caught:
        load_spec(path)
    text = str(caught.value)
    assert "does not exist" in text
    assert "items" in text


def test_unknown_field_and_bpm_range(tmp_path: Path):
    _png(tmp_path)
    path = _write(tmp_path, BASE + "\nmood: loud\nmusic:\n  bpm: 999\n")
    with pytest.raises(SpecError) as caught:
        load_spec(path)
    text = str(caught.value)
    assert "not a recognised field" in text or "bpm" in text


def test_variant_merge_does_not_mutate_master(tmp_path: Path):
    _png(tmp_path)
    path = _write(
        tmp_path,
        BASE
        + """
variants:
  - id: stain
    hook: A different hook
    colours:
      gold: "#E0A15A"
    music:
      bpm: 110
      mood: drive
""",
    )
    spec = load_spec(path)
    original = next(scene.headline for scene in spec.scenes if scene.type == "hook")
    variant = apply_variant(spec, "stain")
    assert next(scene.headline for scene in spec.scenes if scene.type == "hook") == original
    assert next(scene.headline for scene in variant.scenes if scene.type == "hook") == "A different hook"
    assert variant.client.colours.gold[0] == 224
    assert variant.music.bpm == 110
    assert variant.music.mood == "drive"
    assert [name for name, _job in iter_jobs(spec)] == ["master", "stain"]


def test_dark_gold_fails_contrast(tmp_path: Path):
    path = _write(
        tmp_path,
        """
id: sample
client:
  name: Sample
  colours:
    gold: "#222222"
scenes:
  - type: hook
    duration: 2
    headline: Hello
""",
    )
    with pytest.raises(SpecError) as caught:
        load_spec(path)
    assert "contrast" in str(caught.value)


def test_branding_is_inserted_when_omitted(tmp_path: Path):
    path = _write(
        tmp_path,
        """
id: sample
client:
  name: Sample Trades
scenes:
  - type: hook
    duration: 2
    headline: Hello
""",
    )
    spec = load_spec(path)
    assert [scene.type for scene in spec.scenes] == ["intro", "hook", "end"]


def test_script_times_must_be_paired(tmp_path: Path):
    path = _write(
        tmp_path,
        """
id: sample
client:
  name: Sample
scenes:
  - type: hook
    duration: 2
    headline: Hello
script:
  - text: Hello
    start: 1
""",
    )
    with pytest.raises(SpecError) as caught:
        load_spec(path)
    assert "start and end" in str(caught.value)
