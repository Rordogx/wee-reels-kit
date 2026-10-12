from pathlib import Path

import pytest

from wee_reels.formats import FORMATS
from wee_reels.fonts import inter, oswald
from wee_reels.layout import compile_reel, content_limit
from wee_reels.spec import SpecError, load_spec
from wee_reels.textfit import Block, Limit, TextFitError, wrap

ROOT = Path(__file__).resolve().parents[1]


def test_wrap_balances_and_honours_breaks():
    font = inter(28, 500)
    lines = wrap("alpha beta gamma delta epsilon", font, 180, name="sample", where="test")
    assert len(lines) >= 2
    broken = wrap("left side\nright side", font, 400, name="sample", where="test")
    assert broken == ["left side", "right side"]


def test_unbreakable_word_overflows_loudly():
    font = oswald(64, 640)
    with pytest.raises(TextFitError) as caught:
        wrap("Supercalifragilistic", font, 80, name="hook.headline", where="1:1 safe")
    message = str(caught.value)
    assert "OVERFLOW" in message
    assert "hook.headline" in message
    assert "80px" in message


def test_block_inside_safe_area_passes():
    font = oswald(48, 640)
    limit = Limit(90, 990, 220, 1400, "9:16 safe")
    block = Block("A sound roof", font, (243, 238, 228, 255), 90, 280, limit.width, limit, name="hook.headline", rise=20)
    assert block.y >= limit.top
    assert block.bottom + 20 <= limit.bottom
    assert block.lines


def test_block_below_safe_area_fails_with_measurements():
    font = inter(40, 600)
    limit = Limit(80, 1000, 80, 400, "4:5 safe")
    with pytest.raises(TextFitError) as caught:
        Block("Too low", font, (243, 238, 228, 255), 80, 360, limit.width, limit, name="caption", rise=30)
    message = str(caught.value)
    assert "safe y" in message
    assert "caption" in message
    assert "4:5" in message


def test_example_copy_fits_every_format():
    for path in (ROOT / "examples/northlane/reel.yaml", ROOT / "examples/mothbrae/reel.yaml"):
        compiled = compile_reel(load_spec(path))
        assert set(compiled.plans) == {"9:16", "4:5", "1:1"}
        for fmt_id, plan in compiled.plans.items():
            assert plan.captions, fmt_id
            assert plan.scenes[0].slot.scene.type == "intro"


def test_long_token_fails_preflight(tmp_path: Path):
    from PIL import Image

    Image.new("RGB", (4, 4), (0, 0, 0)).save(tmp_path / "a.png")
    spec_path = tmp_path / "reel.yaml"
    spec_path.write_text(
        """
id: overflow
client:
  name: Overflow
scenes:
  - type: hook
    duration: 2
    headline: Supercalifragilisticexpialidocious
""",
        encoding="utf-8",
    )
    with pytest.raises(TextFitError) as caught:
        compile_reel(load_spec(spec_path))
    assert "OVERFLOW" in str(caught.value)


def test_formats_are_different_compositions():
    vertical, feed, square = FORMATS["9:16"], FORMATS["4:5"], FORMATS["1:1"]
    assert (vertical.w, vertical.h) == (1080, 1920)
    assert (feed.w, feed.h) == (1080, 1350)
    assert (square.w, square.h) == (1080, 1080)
    assert vertical.headline > feed.headline > square.headline
    assert vertical.anchor == "l" and square.anchor == "c"
    assert vertical.well == vertical.well and vertical.well != feed.well != square.well
    assert square.well.x > 0
    assert feed.well.bottom < feed.h
    assert content_limit(vertical).bottom < vertical.safe_b
    assert content_limit(square).width != content_limit(vertical).height


def test_caption_band_rejects_a_paragraph(tmp_path: Path):
    spec_path = tmp_path / "reel.yaml"
    spec_path.write_text(
        """
id: caption-overflow
client:
  name: Caption
scenes:
  - type: hook
    duration: 3
    headline: Short
script:
  - "MMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMM"
""",
        encoding="utf-8",
    )
    with pytest.raises(TextFitError) as caught:
        compile_reel(load_spec(spec_path))
    message = str(caught.value)
    assert "OVERFLOW" in message
    assert "caption" in message
