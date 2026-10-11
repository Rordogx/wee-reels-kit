from wee_reels.spec import Scene
from wee_reels.timeline import align_scenes


def _scene(duration: float) -> Scene:
    return Scene(type="hook", duration=duration, headline="Hello")


def test_cuts_land_on_the_beat():
    beat = 0.5
    bounds = align_scenes([_scene(1.0), _scene(1.1), _scene(0.8)], beat, phase=0.0)
    assert bounds[0] == 0.0
    for edge in bounds[1:]:
        assert abs(edge / beat - round(edge / beat)) < 1e-6
    assert bounds == sorted(bounds)
    assert all(b > a for a, b in zip(bounds, bounds[1:]))


def test_short_scene_grows_to_one_beat():
    bounds = align_scenes([_scene(0.2)], beat=0.5, phase=0.0)
    assert bounds == [0.0, 0.5]


def test_phase_offset_keeps_the_grid():
    beat = 0.5
    phase = 0.2
    bounds = align_scenes([_scene(1.0), _scene(1.0)], beat, phase)
    assert bounds[0] == 0.0
    for edge in bounds[1:]:
        offset = (edge - phase) / beat
        assert abs(offset - round(offset)) < 1e-6


def test_exact_multiples_do_not_drift():
    beat = 0.625
    durations = [1.875, 2.5, 3.125, 3.75, 1.875, 2.5]
    bounds = align_scenes([_scene(d) for d in durations], beat, phase=0.0)
    assert abs(bounds[-1] - sum(durations)) < 1e-6
