"""Music, voice, ducking, beat detection, fades, and -14 LUFS with a true-peak limit."""

from __future__ import annotations

import json
import math
import re
import subprocess
import wave
from pathlib import Path

import numpy as np

SR = 48_000


class AudioError(Exception):
    """The mix could not be built or measured."""


def _as_stereo(samples: np.ndarray) -> np.ndarray:
    data = np.asarray(samples, dtype=np.float32)
    if data.ndim == 1:
        data = np.stack([data, data], axis=1)
    if data.shape[1] == 1:
        data = np.repeat(data, 2, axis=1)
    return data


def _mono(samples: np.ndarray) -> np.ndarray:
    data = np.asarray(samples, dtype=np.float64)
    if data.ndim == 2:
        return data.mean(axis=1)
    return data


def read_audio(path: Path) -> tuple[np.ndarray, int]:
    """Decode any file ffmpeg can read to 48 kHz stereo float."""
    cmd = [
        "ffmpeg",
        "-hide_banner",
        "-loglevel",
        "error",
        "-i",
        str(path),
        "-ac",
        "2",
        "-ar",
        str(SR),
        "-f",
        "s16le",
        "-",
    ]
    proc = subprocess.run(cmd, capture_output=True)
    if proc.returncode != 0 or not proc.stdout:
        tail = proc.stderr.decode()[-800:]
        raise AudioError(f"could not read audio {path.name}: {tail}")
    data = np.frombuffer(proc.stdout, dtype=np.int16).astype(np.float32) / 32768.0
    if len(data) < 2:
        raise AudioError(f"audio file is empty: {path.name}")
    return data.reshape(-1, 2), SR


def write_wav(path: Path, samples: np.ndarray, sr: int = SR) -> None:
    stereo = np.clip(_as_stereo(samples), -1, 1)
    pcm = (stereo * 32767.0).astype(np.int16)
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(2)
        handle.setsampwidth(2)
        handle.setframerate(sr)
        handle.writeframes(pcm.tobytes())


def read_wav(path: Path) -> tuple[np.ndarray, int]:
    with wave.open(str(path), "rb") as handle:
        sr = handle.getframerate()
        channels = handle.getnchannels()
        frames = handle.readframes(handle.getnframes())
    data = np.frombuffer(frames, dtype=np.int16).astype(np.float32) / 32768.0
    return data.reshape(-1, channels), sr


def _transients(samples: np.ndarray) -> np.ndarray:
    """A high-passed mono signal, so a steady pad does not hide the beat."""
    mono = _mono(samples)
    mono = np.diff(mono, prepend=mono[0])
    return np.diff(mono, prepend=mono[0])


def _onset_envelope(mono: np.ndarray, sr: int, rate: int = 200) -> tuple[np.ndarray, int]:
    hop = max(1, int(sr / rate))
    frames = len(mono) // hop
    envelope = np.empty(frames, dtype=np.float64)
    for index in range(frames):
        window = mono[index * hop : (index + 1) * hop]
        envelope[index] = math.sqrt(float(np.dot(window, window)) / max(1, len(window)) + 1e-12)
    onset = np.maximum(0.0, np.diff(envelope, prepend=0))
    onset = np.convolve(onset, np.array([0.25, 0.5, 0.25]), mode="same")
    return onset, hop


def detect_bpm(samples: np.ndarray, sr: int = SR, min_bpm: float = 70, max_bpm: float = 160) -> float:
    """Autocorrelation of a transient envelope. Returns the tempo in beats per minute."""
    mono = _transients(samples)
    if len(mono) < sr * 2:
        raise AudioError("need at least 2 seconds of music to detect BPM; set music.bpm")
    rate = 200
    onset, _hop = _onset_envelope(mono, sr, rate)
    onset = onset - onset.mean()
    corr = np.correlate(onset, onset, mode="full")[len(onset) - 1 :]
    min_lag = max(1, int(rate * 60 / max_bpm))
    max_lag = min(len(corr) - 1, int(rate * 60 / min_bpm))
    if max_lag <= min_lag:
        raise AudioError("music is too short to detect BPM; set music.bpm")
    lag = min_lag + int(np.argmax(corr[min_lag : max_lag + 1]))
    return float(60.0 * rate / lag)


def detect_phase(samples: np.ndarray, sr: int = SR, bpm: float = 96) -> float:
    """Time of the first strong onset, used as the beat-grid origin."""
    mono = _transients(samples)
    onset, hop = _onset_envelope(mono, sr, 200)
    if len(onset) < 4:
        return 0.0
    thresh = float(np.percentile(onset, 90))
    hits = np.flatnonzero(onset >= max(thresh, 1e-6))
    if len(hits) == 0:
        return 0.0
    phase = float(hits[0] * hop / sr)
    beat = 60.0 / bpm
    return phase % beat


def synth_music(duration: float, bpm: float, sr: int = SR, mood: str = "warm", seed: int = 1) -> np.ndarray:
    """A short original bed with a kick on every beat, so the grid is audible and detectable."""
    n = int(round(duration * sr))
    rng = np.random.default_rng(seed)
    t = np.arange(n, dtype=np.float64) / sr
    if mood == "drive":
        root, pulse, hat_level = 98.0, 0.9, 0.12
    elif mood == "calm":
        root, pulse, hat_level = 82.0, 0.42, 0.04
    else:
        root, pulse, hat_level = 92.5, 0.62, 0.07
    pad = (
        0.16 * np.sin(2 * np.pi * root * t)
        + 0.10 * np.sin(2 * np.pi * root * 1.498 * t)
        + 0.07 * np.sin(2 * np.pi * root * 2 * t + 0.4)
    )
    pad *= 0.82 + 0.18 * np.sin(2 * np.pi * 0.07 * t)
    beat = 60.0 / bpm
    kick = _kick(sr)
    hat = _hat(sr, rng)
    pulses = np.zeros(n, dtype=np.float64)
    hats = np.zeros(n, dtype=np.float64)
    index = 0
    while index * beat < duration + 1e-6:
        start = int(round(index * beat * sr))
        if 0 <= start < n:
            stop = min(n, start + len(kick))
            pulses[start:stop] += kick[: stop - start]
        off = int(round((index + 0.5) * beat * sr))
        if 0 <= off < n:
            stop = min(n, off + len(hat))
            hats[off:stop] += hat[: stop - off]
        index += 1
    mono = pad + pulses * pulse + hats * hat_level
    delay = int(0.011 * sr)
    right = np.concatenate([np.zeros(delay), mono[: n - delay]]) if delay < n else mono.copy()
    stereo = np.stack([mono, right], axis=1)
    peak = float(np.max(np.abs(stereo))) + 1e-9
    return (stereo * (0.55 / peak)).astype(np.float32)


def _kick(sr: int) -> np.ndarray:
    n = int(0.22 * sr)
    t = np.arange(n) / sr
    freq = 150 * np.exp(-t * 24) + 46
    phase = 2 * np.pi * np.cumsum(freq) / sr
    return np.sin(phase) * np.exp(-t * 14)


def _hat(sr: int, rng: np.random.Generator) -> np.ndarray:
    n = int(0.035 * sr)
    noise = rng.normal(0, 1, n)
    high = np.diff(noise, prepend=0)
    t = np.arange(n) / sr
    return high * np.exp(-t * 110) * 0.8


def synth_whoosh(sr: int = SR) -> np.ndarray:
    dur = 0.48
    n = int(dur * sr)
    rng = np.random.default_rng(2)
    noise = rng.normal(0, 1, n)
    high = np.diff(noise, prepend=0)
    t = np.linspace(0, 1, n)
    env = np.sin(np.pi * t) ** 1.5
    sig = (high * env * 0.5).astype(np.float32)
    right = np.roll(sig, int(0.004 * sr))
    return np.stack([sig, right * 0.9], axis=1)


def synth_tick(sr: int = SR) -> np.ndarray:
    n = int(0.08 * sr)
    t = np.arange(n) / sr
    tone = np.sin(2 * np.pi * 2100 * t) * np.exp(-t * 60)
    click = np.sin(2 * np.pi * 4800 * t) * np.exp(-t * 160)
    sig = (tone * 0.4 + click * 0.22).astype(np.float32)
    return np.stack([sig, sig], axis=1)


def synth_riser(sr: int = SR) -> np.ndarray:
    dur = 1.15
    n = int(dur * sr)
    t = np.arange(n) / sr
    f0, f1 = 180.0, 1500.0
    k = math.log(f1 / f0)
    phase = 2 * math.pi * f0 * dur / k * (np.exp(k * t / dur) - 1)
    body = np.sin(phase) * (t / dur) ** 2
    rng = np.random.default_rng(9)
    air = rng.normal(0, 1, n) * (t / dur) ** 3
    sig = (body * 0.32 + air * 0.05).astype(np.float32)
    detune = np.sin(phase * 1.01) * (t / dur) ** 2 * 0.22
    return np.stack([sig, (sig * 0.8 + detune).astype(np.float32)], axis=1)


def synth_voice(cues: list[tuple[float, float]], duration: float, sr: int = SR, seed: int = 5) -> np.ndarray:
    """Placeholder speech energy so ducking has an envelope. Not a voice performance."""
    n = int(round(duration * sr))
    out = np.zeros((n, 2), np.float32)
    rng = np.random.default_rng(seed)
    for start, end in cues:
        a = int(max(0.0, start) * sr)
        b = int(min(duration, end) * sr)
        if b - a < int(0.05 * sr):
            continue
        seg = b - a
        t = np.arange(seg) / sr
        gate = np.zeros(seg, np.float32)
        step = 0.15
        index = 0
        while index * step < t[-1]:
            s0 = int(index * step * sr)
            length = int(0.09 * sr)
            sl = slice(s0, min(seg, s0 + length))
            tt = np.arange(sl.stop - sl.start) / sr
            gate[sl] += np.exp(-tt * 16).astype(np.float32)
            index += 1
        noise = rng.normal(0, 1, seg).astype(np.float32)
        band = noise - np.convolve(noise, np.ones(80) / 80, mode="same")
        sig = band * gate * 0.45
        out[a:b, 0] += sig
        out[a:b, 1] += sig
    return out


def duck(music: np.ndarray, voice: np.ndarray | None, sr: int = SR, depth: float = 0.22) -> np.ndarray:
    """Pull the bed down while the voiceover has energy, then let it back up."""
    stereo = _as_stereo(music)
    if voice is None:
        return stereo
    voice = _as_stereo(voice)
    length = min(len(stereo), len(voice))
    mono = voice[:length, 0].astype(np.float64)
    hop = max(1, int(sr / 200))
    frames = int(math.ceil(length / hop))
    rms = np.zeros(frames, dtype=np.float64)
    for index in range(frames):
        window = mono[index * hop : (index + 1) * hop]
        if len(window):
            rms[index] = math.sqrt(float(np.dot(window, window)) / len(window) + 1e-12)
    peak = float(np.percentile(rms, 98)) if frames else 0.0
    if peak < 1e-4:
        return stereo
    target = np.where(rms > peak * 0.18, depth, 1.0)
    attack = math.exp(-1 / (0.03 * 200))
    release = math.exp(-1 / (0.34 * 200))
    smoothed = np.empty(frames, dtype=np.float64)
    prev = 1.0
    for index in range(frames):
        coef = attack if target[index] < prev else release
        prev = target[index] + coef * (prev - target[index])
        smoothed[index] = prev
    positions = np.linspace(0, len(stereo) - 1, frames)
    gain = np.interp(np.arange(len(stereo)), positions, smoothed).astype(np.float32)
    out = stereo * gain[:, None]
    return out


def apply_fade(samples: np.ndarray, sr: int, fade_in: float, fade_out: float) -> np.ndarray:
    out = _as_stereo(samples).copy()
    n = len(out)
    fin = min(n // 4, int(fade_in * sr))
    fout = min(n // 2, int(fade_out * sr))
    if fin > 1:
        ramp = np.linspace(0, 1, fin, dtype=np.float32) ** 2
        out[:fin] *= ramp[:, None]
    if fout > 1:
        ramp = np.linspace(1, 0, fout, dtype=np.float32) ** 2
        out[-fout:] *= ramp[:, None]
    return out


def fade_out_seconds(duration: float, beat: float) -> float:
    """A fade of about two beats, longer on a longer reel, never abrupt and never most of the film."""
    return float(np.clip(max(2 * beat, duration * 0.08), 0.45, 2.2))


def fit_length(samples: np.ndarray, n: int, sr: int = SR) -> np.ndarray:
    stereo = _as_stereo(samples)
    if len(stereo) >= n:
        return np.array(stereo[:n], copy=True)
    fade = min(int(0.02 * sr), len(stereo) // 6)
    if fade < 8:
        reps = int(math.ceil(n / len(stereo)))
        return np.vstack([stereo] * reps)[:n]
    window = np.ones(len(stereo), np.float32)
    window[:fade] = np.linspace(0, 1, fade)
    window[-fade:] = np.linspace(1, 0, fade)
    hop = len(stereo) - fade
    out = np.zeros((n + len(stereo), 2), np.float32)
    cursor = 0
    while cursor < n:
        out[cursor : cursor + len(stereo)] += stereo * window[:, None]
        cursor += hop
    return out[:n]


def mix(
    music: np.ndarray,
    voice: np.ndarray | None,
    events: list[tuple[float, np.ndarray]],
    sr: int,
    beat: float,
    duration: float,
) -> np.ndarray:
    ducked = duck(music, voice, sr)
    out = ducked
    if voice is not None:
        voice = _as_stereo(voice)
        n = min(len(out), len(voice))
        out = out.copy()
        out[:n] += voice[:n]
    else:
        out = out.copy()
    for when, samples in events:
        start = int(when * sr)
        if start >= len(out) or start + 8 < 0:
            continue
        piece = _as_stereo(samples)
        left = max(0, start)
        offset = left - start
        stop = min(len(out), start + len(piece))
        if stop > left:
            out[left:stop] += piece[offset : offset + (stop - left)]
    peak = float(np.max(np.abs(out))) if len(out) else 0.0
    if peak > 0.98:
        out *= 0.98 / peak
    return apply_fade(out, sr, fade_in=min(0.2, duration * 0.04), fade_out=fade_out_seconds(duration, beat))


def loudness_normalize(
    samples: np.ndarray,
    sr: int = SR,
    lufs: float = -14.0,
    true_peak: float = -1.5,
) -> tuple[np.ndarray, float, float]:
    """Two-pass loudnorm to the target integrated loudness, then a true-peak limiter."""
    import tempfile

    # Sample-peak ceiling sits under the true-peak target. Intersample peaks
    # run hotter than the sample peak, so the limiter needs that headroom.
    limit = 10 ** ((true_peak - 0.7) / 20)
    with tempfile.TemporaryDirectory(prefix="wee-reels-") as tmp:
        src = Path(tmp) / "in.wav"
        dst = Path(tmp) / "out.wav"
        write_wav(src, samples, sr)
        measure = subprocess.run(
            [
                "ffmpeg",
                "-hide_banner",
                "-i",
                str(src),
                "-af",
                f"loudnorm=I={lufs}:TP={true_peak}:LRA=11:print_format=json",
                "-f",
                "null",
                "-",
            ],
            capture_output=True,
            text=True,
        )
        stats = _parse_loudnorm(measure.stderr)
        for key in ("input_i", "input_tp", "input_lra", "input_thresh", "target_offset"):
            if key not in stats:
                raise AudioError(f"loudnorm did not return {key}")
        if not math.isfinite(float(stats["input_i"])):
            raise AudioError("the mix is silent, so it cannot be normalised to -14 LUFS")
        audio_filter = (
            f"loudnorm=I={lufs}:TP={true_peak}:LRA=11:"
            f"measured_I={stats['input_i']}:measured_TP={stats['input_tp']}:"
            f"measured_LRA={stats['input_lra']}:measured_thresh={stats['input_thresh']}:"
            f"offset={stats['target_offset']}:linear=true,"
            f"alimiter=limit={limit:.5f}:attack=5:release=50:level=disabled"
        )
        rendered = subprocess.run(
            [
                "ffmpeg",
                "-y",
                "-hide_banner",
                "-loglevel",
                "error",
                "-i",
                str(src),
                "-af",
                audio_filter,
                "-ar",
                str(sr),
                "-ac",
                "2",
                "-c:a",
                "pcm_s16le",
                str(dst),
            ],
            capture_output=True,
            text=True,
        )
        if rendered.returncode != 0:
            raise AudioError(f"loudnorm failed:\n{rendered.stderr[-1500:]}")
        normalised, _ = read_wav(dst)
    measured_lufs, measured_tp = measure_loudness_array(normalised, sr)
    if measured_tp > true_peak + 0.05:
        cut_db = measured_tp - true_peak + 0.15
        normalised = normalised * np.float32(10 ** (-cut_db / 20))
        measured_lufs, measured_tp = measure_loudness_array(normalised, sr)
    return normalised, measured_lufs, measured_tp


def measure_loudness_array(samples: np.ndarray, sr: int = SR) -> tuple[float, float]:
    import tempfile

    with tempfile.TemporaryDirectory(prefix="wee-reels-meter-") as tmp:
        path = Path(tmp) / "m.wav"
        write_wav(path, samples, sr)
        return measure_loudness(path)


def measure_loudness(path: Path) -> tuple[float, float]:
    proc = subprocess.run(
        [
            "ffmpeg",
            "-hide_banner",
            "-i",
            str(path),
            "-af",
            "loudnorm=I=-14:TP=-1.5:LRA=11:print_format=json",
            "-f",
            "null",
            "-",
        ],
        capture_output=True,
        text=True,
    )
    stats = _parse_loudnorm(proc.stderr)
    return float(stats["input_i"]), float(stats["input_tp"])


def _parse_loudnorm(text: str) -> dict[str, str]:
    match = re.search(r"\{[^{}]*\"input_i\"[^{}]*\}", text, re.S)
    if not match:
        raise AudioError(f"loudnorm did not report levels:\n{text[-1500:]}")
    data = json.loads(match.group(0))
    return {key: str(value) for key, value in data.items()}
