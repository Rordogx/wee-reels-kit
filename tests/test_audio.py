import numpy as np

from wee_reels.audio import SR, apply_fade, detect_bpm, duck, loudness_normalize, synth_music


def test_detect_bpm_on_a_click_track():
    bpm = 96
    samples = synth_music(8.0, bpm, SR, mood="drive", seed=3)
    found = detect_bpm(samples, SR)
    assert abs(found - bpm) <= 2


def test_detect_bpm_on_calm_and_drive():
    for mood, bpm in (("calm", 84), ("warm", 120)):
        samples = synth_music(8.0, bpm, SR, mood=mood, seed=2)
        assert abs(detect_bpm(samples, SR) - bpm) <= 2


def test_duck_pulls_music_down_under_the_voice():
    sr = 4000
    n = sr * 3
    music = np.ones((n, 2), np.float32) * 0.5
    voice = np.zeros((n, 2), np.float32)
    voice[sr : 2 * sr] = 0.4
    ducked = duck(music, voice, sr, depth=0.22)
    start = float(np.mean(np.abs(ducked[: sr // 2])))
    middle = float(np.mean(np.abs(ducked[int(sr * 1.4) : int(sr * 1.7)])))
    assert middle < start * 0.45


def test_fade_out_reaches_silence():
    samples = np.ones((SR, 2), np.float32) * 0.5
    faded = apply_fade(samples, SR, fade_in=0.05, fade_out=0.3)
    assert float(np.max(np.abs(faded[-int(0.02 * SR) :]))) < 0.05
    assert float(np.max(np.abs(faded[SR // 2]))) > 0.4


def test_loudness_normalise_hits_the_target():
    t = np.arange(SR * 4) / SR
    tone = (0.08 * np.sin(2 * np.pi * 220 * t)).astype(np.float32)
    stereo = np.stack([tone, tone], axis=1)
    normalised, lufs, true_peak = loudness_normalize(stereo, SR, lufs=-14, true_peak=-1.5)
    assert normalised.shape[1] == 2
    assert abs(lufs - (-14)) <= 1.0
    assert true_peak <= -1.5
