# wee-reels-kit

A local Python and ffmpeg toolkit for premium short-form Reels. One YAML or JSON spec renders a client reel at **9:16** (1080×1920), **4:5** (1080×1350) and **1:1** (1080×1080). Each ratio is laid out on its own: type size, alignment, picture well and caption dock all change. Nothing is a crop of the vertical master.

The look follows the house style of the brand's best ads. A dark charcoal field carries grain, a vignette, a faint grid and a warm glow that drifts. Headlines are Oswald, body and captions are Inter, tags are gold and letter-spaced, gold rules draw on, lines rise in a stagger, a beam wipes before into after, checklist rows tick in, and the end card closes on a gold pill. Type that leaves the safe area fails the render before a single frame is encoded.

No accounts, no paid APIs, no client data. Music, placeholder voice and the whoosh, tick and riser are synthesised in the kit. Drop in your own stems when you have them.

## Quick start

You need Python 3.11+ and ffmpeg (libx264, aac, and the `loudnorm` filter, which a normal build already has).

```bash
pip install -e ".[dev]"
python examples/build_assets.py   # fictional stills, already in the repo
wee-reels validate examples/northlane/reel.yaml
wee-reels render examples/northlane/reel.yaml -o dist
wee-reels render examples/mothbrae/reel.yaml -o dist
```

`wee-reels` is installed as a console script. If it is not on your `PATH`, run `python -m wee_reels` instead.

That writes six files:

```text
dist/northlane/master/northlane_9x16.mp4    # 1080×1920
dist/northlane/master/northlane_4x5.mp4     # 1080×1350
dist/northlane/master/northlane_1x1.mp4     # 1080×1080
dist/mothbrae/master/mothbrae_9x16.mp4
dist/mothbrae/master/mothbrae_4x5.mp4
dist/mothbrae/master/mothbrae_1x1.mp4
```

Northlane is a fictional roofer. Mothbrae is a fictional holiday lodge. Phones use the Ofcom drama range (01632) and the sites are `.example`. The stills are drawn placeholders, not photographs.

A render prints the tempo, the length, and the measured mix. A local batch of both examples came out as:

| reel | integrated | true peak |
| --- | --- | --- |
| Northlane master | -14.7 LUFS | -1.8 dBTP |
| Mothbrae master | -15.1 LUFS | -1.7 dBTP |

The calmer lodge bed sits a little under -14 because the true-peak ceiling binds before the integrated target. Both stay under the -1.5 dBTP limit.

Batch renders the master and every variant (a different hook, a different tempo and mood, a different gold) in one command:

```bash
wee-reels batch examples/northlane/reel.yaml -o dist
wee-reels batch examples/mothbrae/reel.yaml -o dist
```

Variants land next to the master: `dist/northlane/stain/northlane_9x16.mp4`, `dist/northlane/champagne/…`, `dist/mothbrae/weeknight/…`, `dist/mothbrae/after-frost/…`.

Render a subset while you are tuning copy:

```bash
wee-reels render examples/northlane/reel.yaml -o dist --formats 1:1 --variant stain
```

`validate` checks the spec, snaps the cut list to the beat, and runs the safe-area text-fit on every format. It does not encode. `--verbose` prints every line's box.

```bash
python -m pytest
```

## What a spec contains

```yaml
id: northlane                 # filename slug
client:
  name: Northlane Roofing     # required
  trade: Roofing              # gold tag on the intro and end card
  tagline: Roofs that stay put
  phone: "01632 960014"       # keep phone numbers quoted
  web: northlane.example
  logo: assets/logo.png       # optional; a monogram is drawn if you omit it
  colours:
    gold: "#E8B23A"
    ink: "#F3EEE4"
    muted: "#AAA69E"
    charcoal: "#141416"
    glow: "#E89628"
music:
  bpm: 96                     # omit to detect it from music.file
  mood: warm                  # warm, calm, or drive — only used by the synth
  # file: assets/bed.wav      # wav, mp3, m4a, … looped or trimmed to the reel
voiceover:
  synth: true                 # placeholder speech energy so the bed ducks
  # file: assets/vo.wav       # a real read replaces the synth
captions:
  timing: line                # line: one caption per scene, or spread evenly
  # timing: beat              # beat: each line lasts beats_per_line beats
  beats_per_line: 3
sfx:
  whoosh: true                # on the beam
  tick: true                  # as each checklist row lands
  riser: true                 # into the end card
audio:
  lufs: -14                   # integrated loudness
  true_peak: -1.5             # dBTP ceiling
formats: ["9:16", "4:5", "1:1"]
scenes: []                    # see below
script: []                    # burned-in captions
variants: []                  # batch hooks, colours, music, scripts
```

JSON works the same way. Paths are relative to the spec file.

If you leave out an intro or an end card, the kit inserts the client's intro and outro. An explicit `intro` or `end` (or `outro`, same template) is kept and not duplicated.

### Scenes

| type | role |
| --- | --- |
| `intro` | Trade tag, logo or monogram, name, a gold rule that draws on, tagline |
| `hook` | Letter-spaced tag, Oswald headline, rule, muted sub |
| `before_after` | Two stills or clips. A beam wipes left to right, with a whoosh |
| `checklist` | Title, then rows that tick in |
| `title` | A centred title card |
| `end` / `outro` | Logo, name, rule, gold pill, web and phone |

`before` and `after` accept png, jpg, webp, mp4, mov, webm, m4v or mkv. A clip is cover-fitted into that format's picture well and looped if it is shorter than the scene. Stills drift a little (a short ken burns) inside the same well.

Picture wells are not the same rectangle:

- **9:16** is full bleed. Labels and captions sit on the picture, inside the safe box.
- **4:5** keeps the picture full width and stops above a charcoal caption dock.
- **1:1** is a centred card on the charcoal field, with the label above the card and the caption below it. Type is centred. On the taller formats it stays left-aligned, in the editorial arrangement.

Durations are in seconds. After the open, every cut snaps to the beat. A scene is never shorter than one beat, and it will not be squeezed below about three quarters of the duration you asked for. Set `music.bpm`, or omit it and pass `music.file` and the tempo is detected from the transients.

### Captions

`script` is a list of strings, or `{text, start, end}` on every line. With `timing: line` and one line per content scene (everything except the intro and the end card), each line is burned in for that scene. Otherwise the lines share the middle of the reel evenly. `timing: beat` starts on the grid and holds each line for `beats_per_line`.

Captions are not drawn over the intro or the end card. A line timed entirely inside those scenes is an error. The caption sits in a band at the bottom of the safe area, in a dark pill with a hairline gold edge, and it has to fit that band.

### Safe area

The vertical safe box matches the house style: left 90, right 990, top 220, bottom 1570, with the caption band inside it. 4:5 and 1:1 have their own boxes, inset from the platform UI. Headlines, subs, checklist rows, pills and captions are measured in that box, including the pixels they travel while they rise on.

If a line cannot wrap into the box, the command exits with code 3 and names the block:

```text
text does not fit [1:1 caption] caption: OVERFLOW "MMMM…" is 980px wide, safe width is 860px
```

Code 2 is a spec error (unknown field, missing still, a gold that disappears on the charcoal, a caption list that runs past the end of the reel). Fix the copy or the timing. The kit does not silently shrink type or clip it.

Ink, gold and muted each have to clear a contrast ratio against the charcoal, so a variant cannot ship a gold that vanishes.

### Audio

The master is normalised to **-14 LUFS** integrated, then held to a **-1.5 dBTP** true-peak ceiling (both configurable under `audio`). The sample limiter sits a little under the ceiling, because inter-sample peaks run hotter than the sample peak; if a mix still pokes through, the whole master is trimmed until the measured true peak is under the limit. A very dynamic bed can therefore land a fraction under -14 LUFS. That is the limiter doing its job.

While the voiceover has energy the bed ducks to about a fifth of its level, then eases back over a third of a second. The synth voice is only there so the duck has an envelope. Point `voiceover.file` at a real read and the same sidechain follows that file. The examples leave `synth: true` so the Northlane and Mothbrae masters demonstrate the duck: full level on the intro and the end card, tucked under the captions in between.

The bed fades in over a short breath and fades out over about two beats, longer on a longer reel, capped so the fade is never most of the film. Whoosh, tick and riser are optional and timed to the wipe, the ticks and the end card.

### Variants

A variant replaces the first hook, and can replace its sub and tag, the end-card call to action, any brand colour, the music tempo, mood or file, and the whole caption script.

```yaml
variants:
  - id: stain
    hook: "That stain started on the roof"
    music:
      bpm: 108
      mood: drive
    colours:
      gold: "#E0A15A"
    script:
      - "That stain on the ceiling started on the roof."
```

`wee-reels batch` renders `master` plus each variant, at every format in the spec.

## Layout of the repo

```text
src/wee_reels/     spec, safe-area type, scenes, audio, ffmpeg encode
src/wee_reels/fonts/   Oswald (variable) and Inter, SIL Open Font License
examples/northlane/    fictional roofer
examples/mothbrae/     fictional lodge
examples/build_assets.py
tests/                 spec validation, text-fit, beat grid, loudness, a short render
```

## Tests

```bash
python -m pytest
```

Spec validation covers missing fields, unknown scene types, bad colours, missing media, contrast, variant merging, and JSON. Text-fit covers wrapping, hard line breaks, overflow, a block that falls out of the safe box, and both example specs at all three formats. Audio tests cover tempo detection, ducking, the fade, and the -14 LUFS / -1.5 dBTP master.
