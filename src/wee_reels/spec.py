"""Load and validate a reel spec. Unknown fields and missing media fail before any frames are drawn."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, replace
from pathlib import Path

import yaml

from wee_reels.formats import canonical_format

SLUG = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
HEX = re.compile(r"^#([0-9a-fA-F]{3}|[0-9a-fA-F]{6})$")
SCENE_TYPES = {"intro", "hook", "before_after", "checklist", "title", "end", "outro"}
MOODS = {"warm", "calm", "drive"}
MEDIA_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp", ".mp4", ".mov", ".webm", ".m4v", ".mkv"}
AUDIO_SUFFIXES = {".wav", ".mp3", ".m4a", ".aac", ".flac", ".ogg"}
COLOUR_KEYS = ("gold", "ink", "muted", "charcoal", "glow")


class SpecError(Exception):
    def __init__(self, errors: list[str], path: str | None = None) -> None:
        self.errors = errors
        self.path = path
        lines = "\n".join(f"- {error}" for error in errors)
        head = f"{path}: invalid reel spec" if path else "invalid reel spec"
        super().__init__(f"{head}\n{lines}")


@dataclass(frozen=True)
class Colours:
    gold: tuple[int, int, int, int]
    ink: tuple[int, int, int, int]
    muted: tuple[int, int, int, int]
    charcoal: tuple[int, int, int, int]
    glow: tuple[int, int, int, int]


DEFAULT_COLOURS = Colours(
    gold=(232, 178, 58, 255),
    ink=(243, 238, 228, 255),
    muted=(170, 166, 158, 255),
    charcoal=(20, 20, 22, 255),
    glow=(232, 150, 40, 255),
)


@dataclass(frozen=True)
class Client:
    name: str
    trade: str
    tagline: str
    phone: str
    web: str
    logo: str
    colours: Colours


@dataclass(frozen=True)
class Music:
    file: str
    bpm: float | None
    mood: str


@dataclass(frozen=True)
class Voiceover:
    file: str
    synth: bool


@dataclass(frozen=True)
class Captions:
    timing: str
    beats_per_line: int


@dataclass(frozen=True)
class Sfx:
    whoosh: bool
    tick: bool
    riser: bool


@dataclass(frozen=True)
class AudioSpec:
    lufs: float
    true_peak: float


@dataclass(frozen=True)
class Scene:
    type: str
    duration: float
    tag: str = ""
    headline: str = ""
    sub: str = ""
    title: str = ""
    items: tuple[str, ...] = ()
    before: str = ""
    after: str = ""
    before_label: str = "Before"
    after_label: str = "After"
    cta: str = ""
    line: str = ""
    plate: str = ""


@dataclass(frozen=True)
class ScriptLine:
    text: str
    start: float | None = None
    end: float | None = None


@dataclass(frozen=True)
class Variant:
    id: str
    hook: str | None = None
    sub: str | None = None
    tag: str | None = None
    cta: str | None = None
    colours: tuple[tuple[str, tuple[int, int, int, int]], ...] = ()
    music: tuple[tuple[str, object], ...] = ()
    script: tuple[ScriptLine, ...] | None = None


@dataclass(frozen=True)
class ReelSpec:
    source: Path
    version: int
    id: str
    client: Client
    music: Music
    voiceover: Voiceover
    captions: Captions
    sfx: Sfx
    audio: AudioSpec
    formats: tuple[str, ...]
    scenes: tuple[Scene, ...]
    script: tuple[ScriptLine, ...]
    variants: tuple[Variant, ...]
    seed: int
    fps: int
    variant_id: str = "master"

    def resolve(self, relative: str) -> Path:
        path = Path(relative)
        if path.is_absolute():
            return path
        return self.source.parent / path


def contrast_ratio(a: tuple[int, int, int, int], b: tuple[int, int, int, int]) -> float:
    def channel(value: int) -> float:
        c = value / 255
        return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4

    def lum(colour: tuple[int, int, int, int]) -> float:
        r, g, b = (channel(colour[0]), channel(colour[1]), channel(colour[2]))
        return 0.2126 * r + 0.7152 * g + 0.0722 * b

    lighter, darker = sorted((lum(a), lum(b)), reverse=True)
    return (lighter + 0.05) / (darker + 0.05)


def load_spec(path: Path | str) -> ReelSpec:
    source = Path(path)
    if not source.is_file():
        raise SpecError([f"file not found: {source}"], str(source))
    text = source.read_text(encoding="utf-8")
    try:
        if source.suffix.lower() == ".json":
            raw = json.loads(text)
        else:
            raw = yaml.safe_load(text)
    except (json.JSONDecodeError, yaml.YAMLError) as exc:
        raise SpecError([f"could not parse {source.suffix or 'file'}: {exc}"], str(source)) from exc
    errors: list[str] = []
    spec = _parse(raw, source, errors)
    if errors:
        raise SpecError(errors, str(source))
    assert spec is not None
    return spec


def apply_variant(spec: ReelSpec, variant_id: str) -> ReelSpec:
    if variant_id in ("master", "base", ""):
        return spec
    matches = [item for item in spec.variants if item.id == variant_id]
    if not matches:
        known = ", ".join(item.id for item in spec.variants) or "none"
        raise SpecError([f"no variant {variant_id!r} (have: {known})"], str(spec.source))
    variant = matches[0]
    colours = spec.client.colours
    if variant.colours:
        colours = replace(colours, **dict(variant.colours))
    client = replace(spec.client, colours=colours)
    music = replace(spec.music, **dict(variant.music)) if variant.music else spec.music
    scenes: list[Scene] = []
    hooked = False
    for scene in spec.scenes:
        if scene.type == "hook" and not hooked and (variant.hook or variant.sub is not None or variant.tag is not None):
            scene = replace(
                scene,
                headline=variant.hook or scene.headline,
                sub=variant.sub if variant.sub is not None else scene.sub,
                tag=variant.tag if variant.tag is not None else scene.tag,
            )
            hooked = True
        if scene.type in ("end", "outro") and variant.cta:
            scene = replace(scene, cta=variant.cta)
        scenes.append(scene)
    if (variant.hook or variant.sub is not None or variant.tag is not None) and not hooked:
        raise SpecError(
            [f"variant {variant.id!r} changes the hook, but the reel has no hook scene"],
            str(spec.source),
        )
    script = variant.script if variant.script is not None else spec.script
    return replace(
        spec,
        client=client,
        music=music,
        scenes=tuple(scenes),
        script=script,
        variant_id=variant.id,
    )


def iter_jobs(spec: ReelSpec) -> list[tuple[str, ReelSpec]]:
    jobs = [("master", spec)]
    for variant in spec.variants:
        jobs.append((variant.id, apply_variant(spec, variant.id)))
    return jobs


def _parse(raw: object, source: Path, errors: list[str]) -> ReelSpec | None:
    if not isinstance(raw, dict):
        errors.append("the spec must be a mapping")
        return None
    allowed = {
        "version",
        "id",
        "seed",
        "fps",
        "client",
        "music",
        "voiceover",
        "captions",
        "sfx",
        "audio",
        "formats",
        "scenes",
        "script",
        "variants",
    }
    _unknown(raw, allowed, "spec", errors)
    version = raw.get("version", 1)
    if version != 1:
        errors.append("version must be 1")
    reel_id = _slug(raw.get("id"), "id", errors)
    seed = _int(raw.get("seed", 1), "seed", errors, 0, 10_000)
    fps = _int(raw.get("fps", 24), "fps", errors, 12, 60)
    client = _client(raw.get("client"), source, errors)
    music = _music(raw.get("music", {}), source, errors)
    voice = _voice(raw.get("voiceover", {}), source, errors)
    captions = _captions(raw.get("captions", {}), errors)
    sfx = _sfx(raw.get("sfx", {}), errors)
    audio = _audio(raw.get("audio", {}), errors)
    formats = _formats(raw.get("formats", ["9:16", "4:5", "1:1"]), errors)
    scenes = _scenes(raw.get("scenes"), source, errors)
    script = _script(raw.get("script", []), errors)
    variants = _variants(raw.get("variants", []), errors, source)
    if client is None or scenes is None:
        return None
    _contrast(client.colours, errors)
    for variant in variants:
        if variant.colours:
            merged = replace(client.colours, **dict(variant.colours))
            _contrast(merged, errors, prefix=f"variant {variant.id} colours")
    scenes = _ensure_branding(scenes)
    return ReelSpec(
        source=source,
        version=1,
        id=reel_id or "reel",
        client=client,
        music=music,
        voiceover=voice,
        captions=captions,
        sfx=sfx,
        audio=audio,
        formats=formats,
        scenes=tuple(scenes),
        script=script,
        variants=variants,
        seed=seed,
        fps=fps,
    )


def _ensure_branding(scenes: list[Scene]) -> list[Scene]:
    out = list(scenes)
    if not out or out[0].type != "intro":
        out.insert(0, Scene(type="intro", duration=1.875))
    if out[-1].type not in ("end", "outro"):
        out.append(Scene(type="end", duration=2.5, cta="Get in touch"))
    return out


def _contrast(colours: Colours, errors: list[str], prefix: str = "client.colours") -> None:
    checks = (
        ("ink", colours.ink, 4.5),
        ("gold", colours.gold, 3.0),
        ("muted", colours.muted, 2.4),
    )
    for name, colour, minimum in checks:
        ratio = contrast_ratio(colour, colours.charcoal)
        if ratio < minimum:
            errors.append(
                f"{prefix}.{name} contrast on charcoal is {ratio:.2f}:1, need at least {minimum:.1f}:1"
            )


def _client(raw: object, source: Path, errors: list[str]) -> Client | None:
    if not isinstance(raw, dict):
        errors.append("client is required")
        return None
    _unknown(raw, {"name", "trade", "tagline", "phone", "web", "logo", "colours"}, "client", errors)
    name = _text(raw.get("name"), "client.name", errors, required=True)
    trade = _text(raw.get("trade", ""), "client.trade", errors)
    tagline = _text(raw.get("tagline", ""), "client.tagline", errors)
    phone = _text(raw.get("phone", ""), "client.phone", errors)
    web = _text(raw.get("web", ""), "client.web", errors)
    logo = _text(raw.get("logo", ""), "client.logo", errors)
    if logo:
        _media_file(source, logo, "client.logo", errors, AUDIO_SUFFIXES | MEDIA_SUFFIXES, kind="image")
    colours = _colours(raw.get("colours", {}), errors)
    if not name or colours is None:
        return None
    return Client(name=name, trade=trade, tagline=tagline, phone=phone, web=web, logo=logo, colours=colours)


def _colours(raw: object, errors: list[str]) -> Colours | None:
    if raw is None:
        raw = {}
    if not isinstance(raw, dict):
        errors.append("client.colours must be a mapping")
        return None
    _unknown(raw, set(COLOUR_KEYS), "client.colours", errors)
    values = {}
    defaults = {
        "gold": DEFAULT_COLOURS.gold,
        "ink": DEFAULT_COLOURS.ink,
        "muted": DEFAULT_COLOURS.muted,
        "charcoal": DEFAULT_COLOURS.charcoal,
        "glow": DEFAULT_COLOURS.glow,
    }
    ok = True
    for key, default in defaults.items():
        if key not in raw:
            values[key] = default
            continue
        parsed = _hex(raw[key], f"client.colours.{key}", errors)
        if parsed is None:
            ok = False
        else:
            values[key] = parsed
    if not ok:
        return None
    return Colours(**values)


def _music(raw: object, source: Path, errors: list[str]) -> Music:
    if raw is None:
        raw = {}
    if not isinstance(raw, dict):
        errors.append("music must be a mapping")
        return Music(file="", bpm=96, mood="warm")
    _unknown(raw, {"file", "bpm", "mood"}, "music", errors)
    file = _text(raw.get("file", ""), "music.file", errors)
    if file:
        _media_file(source, file, "music.file", errors, AUDIO_SUFFIXES, kind="audio")
    bpm = None
    if "bpm" in raw and raw["bpm"] is not None:
        bpm = _number(raw["bpm"], "music.bpm", errors, 40, 200)
    mood = _choice(raw.get("mood", "warm"), "music.mood", MOODS, errors)
    return Music(file=file, bpm=bpm, mood=mood)


def _voice(raw: object, source: Path, errors: list[str]) -> Voiceover:
    if raw is None:
        raw = {}
    if not isinstance(raw, dict):
        errors.append("voiceover must be a mapping")
        return Voiceover(file="", synth=False)
    _unknown(raw, {"file", "synth"}, "voiceover", errors)
    file = _text(raw.get("file", ""), "voiceover.file", errors)
    if file:
        _media_file(source, file, "voiceover.file", errors, AUDIO_SUFFIXES, kind="audio")
    synth = raw.get("synth", False)
    if not isinstance(synth, bool):
        errors.append("voiceover.synth must be true or false")
        synth = False
    return Voiceover(file=file, synth=synth)


def _captions(raw: object, errors: list[str]) -> Captions:
    if raw is None:
        raw = {}
    if not isinstance(raw, dict):
        errors.append("captions must be a mapping")
        return Captions(timing="line", beats_per_line=2)
    _unknown(raw, {"timing", "beats_per_line"}, "captions", errors)
    timing = _choice(raw.get("timing", "line"), "captions.timing", {"line", "beat"}, errors)
    beats = _int(raw.get("beats_per_line", 2), "captions.beats_per_line", errors, 1, 8)
    return Captions(timing=timing, beats_per_line=beats)


def _sfx(raw: object, errors: list[str]) -> Sfx:
    if raw is None:
        raw = {}
    if not isinstance(raw, dict):
        errors.append("sfx must be a mapping")
        return Sfx(True, True, True)
    _unknown(raw, {"whoosh", "tick", "riser"}, "sfx", errors)
    flags = {}
    for key in ("whoosh", "tick", "riser"):
        value = raw.get(key, True)
        if not isinstance(value, bool):
            errors.append(f"sfx.{key} must be true or false")
            value = True
        flags[key] = value
    return Sfx(**flags)


def _audio(raw: object, errors: list[str]) -> AudioSpec:
    if raw is None:
        raw = {}
    if not isinstance(raw, dict):
        errors.append("audio must be a mapping")
        return AudioSpec(-14.0, -1.5)
    _unknown(raw, {"lufs", "true_peak"}, "audio", errors)
    lufs = _number(raw.get("lufs", -14), "audio.lufs", errors, -24, -8)
    true_peak = _number(raw.get("true_peak", -1.5), "audio.true_peak", errors, -6, -0.1)
    return AudioSpec(lufs=lufs, true_peak=true_peak)


def _formats(raw: object, errors: list[str]) -> tuple[str, ...]:
    if not isinstance(raw, list) or not raw:
        errors.append("formats must be a non-empty list")
        return ("9:16", "4:5", "1:1")
    out: list[str] = []
    for index, item in enumerate(raw):
        if not isinstance(item, str):
            errors.append(f"formats[{index}] must be a string")
            continue
        canonical = canonical_format(item)
        if canonical is None:
            errors.append(f"formats[{index}] {item!r} is not 9:16, 4:5, or 1:1")
            continue
        if canonical in out:
            errors.append(f"formats lists {canonical} more than once")
            continue
        out.append(canonical)
    return tuple(out) or ("9:16", "4:5", "1:1")


def _scenes(raw: object, source: Path, errors: list[str]) -> list[Scene] | None:
    if not isinstance(raw, list) or not raw:
        errors.append("scenes must be a non-empty list")
        return None
    scenes: list[Scene] = []
    for index, item in enumerate(raw):
        scene = _scene(item, index, source, errors)
        if scene is not None:
            scenes.append(scene)
    return scenes


def _scene(raw: object, index: int, source: Path, errors: list[str]) -> Scene | None:
    path = f"scenes[{index}]"
    if not isinstance(raw, dict):
        errors.append(f"{path} must be a mapping")
        return None
    allowed = {
        "type",
        "duration",
        "tag",
        "headline",
        "sub",
        "title",
        "items",
        "before",
        "after",
        "before_label",
        "after_label",
        "cta",
        "line",
        "plate",
    }
    _unknown(raw, allowed, path, errors)
    kind = raw.get("type")
    if kind not in SCENE_TYPES:
        errors.append(f"{path}.type {kind!r} is not a scene type ({', '.join(sorted(SCENE_TYPES))})")
        return None
    duration = _number(raw.get("duration"), f"{path}.duration", errors, 0.4, 30)
    tag = _text(raw.get("tag", ""), f"{path}.tag", errors)
    headline = _text(raw.get("headline", ""), f"{path}.headline", errors)
    sub = _text(raw.get("sub", ""), f"{path}.sub", errors)
    title = _text(raw.get("title", ""), f"{path}.title", errors)
    cta = _text(raw.get("cta", ""), f"{path}.cta", errors)
    line = _text(raw.get("line", ""), f"{path}.line", errors)
    before_label = _text(raw.get("before_label", "Before"), f"{path}.before_label", errors) or "Before"
    after_label = _text(raw.get("after_label", "After"), f"{path}.after_label", errors) or "After"
    before = _text(raw.get("before", ""), f"{path}.before", errors)
    after = _text(raw.get("after", ""), f"{path}.after", errors)
    plate = _text(raw.get("plate", ""), f"{path}.plate", errors)
    items = _items(raw.get("items", []), f"{path}.items", errors)
    if kind == "hook" and not headline:
        errors.append(f"{path}.headline is required for a hook")
    if kind == "title" and not headline:
        errors.append(f"{path}.headline is required for a title card")
    if kind == "checklist" and not items:
        errors.append(f"{path}.items needs at least one line")
    if kind == "before_after":
        if not before or not after:
            errors.append(f"{path} needs before and after media")
        if before:
            _media_file(source, before, f"{path}.before", errors, MEDIA_SUFFIXES, kind="media")
        if after:
            _media_file(source, after, f"{path}.after", errors, MEDIA_SUFFIXES, kind="media")
    if plate:
        _media_file(source, plate, f"{path}.plate", errors, MEDIA_SUFFIXES, kind="media")
    if duration is None:
        return None
    return Scene(
        type=str(kind),
        duration=duration,
        tag=tag,
        headline=headline,
        sub=sub,
        title=title,
        items=tuple(items),
        before=before,
        after=after,
        before_label=before_label,
        after_label=after_label,
        cta=cta,
        line=line,
        plate=plate,
    )


def _items(raw: object, path: str, errors: list[str]) -> list[str]:
    if raw is None:
        return []
    if not isinstance(raw, list):
        errors.append(f"{path} must be a list of strings")
        return []
    items = []
    for index, item in enumerate(raw):
        text = _text(item, f"{path}[{index}]", errors, required=True)
        if text:
            items.append(text)
    return items


def _script(raw: object, errors: list[str], path: str = "script") -> tuple[ScriptLine, ...]:
    if raw is None:
        return ()
    if not isinstance(raw, list):
        errors.append(f"{path} must be a list")
        return ()
    lines: list[ScriptLine] = []
    timed = 0
    for index, item in enumerate(raw):
        here = f"{path}[{index}]"
        if isinstance(item, str):
            text = _text(item, here, errors, required=True)
            if text:
                lines.append(ScriptLine(text=text))
            continue
        if not isinstance(item, dict):
            errors.append(f"{here} must be a string or a mapping")
            continue
        _unknown(item, {"text", "start", "end"}, here, errors)
        text = _text(item.get("text"), f"{here}.text", errors, required=True)
        start = item.get("start")
        end = item.get("end")
        if (start is None) ^ (end is None):
            errors.append(f"{here} needs both start and end, or neither")
        parsed_start = _number(start, f"{here}.start", errors, 0, 120) if start is not None else None
        parsed_end = _number(end, f"{here}.end", errors, 0, 180) if end is not None else None
        if parsed_start is not None and parsed_end is not None and parsed_end <= parsed_start:
            errors.append(f"{here}.end must be after start")
        if start is not None:
            timed += 1
        if text:
            lines.append(ScriptLine(text=text, start=parsed_start, end=parsed_end))
    if timed and timed != len(lines):
        errors.append(f"{path} lines must all carry start and end, or none of them")
    return tuple(lines)


def _variants(raw: object, errors: list[str], source: Path) -> tuple[Variant, ...]:
    if raw is None:
        return ()
    if not isinstance(raw, list):
        errors.append("variants must be a list")
        return ()
    variants: list[Variant] = []
    seen: set[str] = set()
    for index, item in enumerate(raw):
        path = f"variants[{index}]"
        if not isinstance(item, dict):
            errors.append(f"{path} must be a mapping")
            continue
        _unknown(item, {"id", "hook", "sub", "tag", "cta", "colours", "music", "script"}, path, errors)
        vid = _slug(item.get("id"), f"{path}.id", errors)
        if not vid:
            continue
        if vid in seen or vid == "master":
            errors.append(f"{path}.id {vid!r} is repeated or reserved")
            continue
        seen.add(vid)
        hook = _optional_text(item, "hook", path, errors)
        sub = _optional_text(item, "sub", path, errors)
        tag = _optional_text(item, "tag", path, errors)
        cta = _optional_text(item, "cta", path, errors)
        colours = _variant_colours(item.get("colours"), f"{path}.colours", errors) if "colours" in item else ()
        music = _variant_music(item.get("music"), f"{path}.music", errors, source) if "music" in item else ()
        script = _script(item["script"], errors, path=f"{path}.script") if "script" in item else None
        variants.append(
            Variant(id=vid, hook=hook, sub=sub, tag=tag, cta=cta, colours=colours, music=music, script=script)
        )
    return tuple(variants)


def _variant_colours(raw: object, path: str, errors: list[str]) -> tuple[tuple[str, tuple[int, int, int, int]], ...]:
    if not isinstance(raw, dict):
        errors.append(f"{path} must be a mapping")
        return ()
    _unknown(raw, set(COLOUR_KEYS), path, errors)
    out = []
    for key, value in raw.items():
        if key not in COLOUR_KEYS:
            continue
        parsed = _hex(value, f"{path}.{key}", errors)
        if parsed is not None:
            out.append((key, parsed))
    return tuple(out)


def _variant_music(raw: object, path: str, errors: list[str], source: Path) -> tuple[tuple[str, object], ...]:
    if not isinstance(raw, dict):
        errors.append(f"{path} must be a mapping")
        return ()
    _unknown(raw, {"file", "bpm", "mood"}, path, errors)
    out: list[tuple[str, object]] = []
    if "bpm" in raw:
        bpm = _number(raw["bpm"], f"{path}.bpm", errors, 40, 200)
        if bpm is not None:
            out.append(("bpm", bpm))
    if "mood" in raw:
        out.append(("mood", _choice(raw["mood"], f"{path}.mood", MOODS, errors)))
    if "file" in raw:
        file = _text(raw["file"], f"{path}.file", errors)
        if file:
            _media_file(source, file, f"{path}.file", errors, AUDIO_SUFFIXES, kind="audio")
        out.append(("file", file))
    return tuple(out)


def _optional_text(raw: dict, key: str, path: str, errors: list[str]) -> str | None:
    if key not in raw:
        return None
    return _text(raw[key], f"{path}.{key}", errors)


def _media_file(source: Path, relative: str, path: str, errors: list[str], suffixes: set[str], kind: str) -> None:
    suffix = Path(relative).suffix.lower()
    if kind == "image" and suffix not in {".png", ".jpg", ".jpeg", ".webp"}:
        errors.append(f"{path} must be a png, jpg, or webp")
        return
    if suffix not in suffixes:
        errors.append(f"{path} has an unsupported {kind} type {suffix or '(none)'}")
        return
    resolved = relative if Path(relative).is_absolute() else source.parent / relative
    if not Path(resolved).is_file():
        errors.append(f"{path} does not exist: {relative}")


def _unknown(raw: dict, allowed: set[str], path: str, errors: list[str]) -> None:
    for key in raw:
        if key not in allowed:
            errors.append(f"{path}.{key} is not a recognised field")


def _slug(value: object, path: str, errors: list[str]) -> str:
    if not isinstance(value, str) or not SLUG.match(value):
        errors.append(f"{path} must be a lowercase slug (a-z, 0-9, hyphens)")
        return ""
    return value


def _text(value: object, path: str, errors: list[str], required: bool = False) -> str:
    if value is None:
        if required:
            errors.append(f"{path} is required")
        return ""
    if not isinstance(value, str):
        errors.append(f"{path} must be a string")
        return ""
    cleaned = value.replace("\r\n", "\n").strip()
    if required and not cleaned:
        errors.append(f"{path} is required")
    return cleaned


def _choice(value: object, path: str, options: set[str], errors: list[str]) -> str:
    if not isinstance(value, str) or value not in options:
        errors.append(f"{path} must be one of: {', '.join(sorted(options))}")
        return sorted(options)[0]
    return value


def _number(value: object, path: str, errors: list[str], lo: float, hi: float) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        errors.append(f"{path} must be a number")
        return None
    number = float(value)
    if not lo <= number <= hi:
        errors.append(f"{path} must be between {lo:g} and {hi:g}")
        return None
    return number


def _int(value: object, path: str, errors: list[str], lo: int, hi: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        errors.append(f"{path} must be an integer")
        return lo
    if not lo <= value <= hi:
        errors.append(f"{path} must be between {lo} and {hi}")
        return lo
    return value


def _hex(value: object, path: str, errors: list[str]) -> tuple[int, int, int, int] | None:
    if not isinstance(value, str) or not HEX.match(value):
        errors.append(f"{path} must be a hex colour like #E8B23A")
        return None
    body = value[1:]
    if len(body) == 3:
        body = "".join(ch * 2 for ch in body)
    r = int(body[0:2], 16)
    g = int(body[2:4], 16)
    b = int(body[4:6], 16)
    return (r, g, b, 255)
