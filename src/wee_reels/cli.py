"""Command line for wee-reels."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from wee_reels.audio import AudioError
from wee_reels.formats import canonical_format
from wee_reels.layout import compile_reel
from wee_reels.render import render_batch, render_reel, report
from wee_reels.spec import SpecError, apply_variant, load_spec
from wee_reels.textfit import TextFitError


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="wee-reels", description="Premium short-form Reels from a YAML or JSON spec.")
    sub = parser.add_subparsers(dest="cmd", required=True)

    validate = sub.add_parser("validate", help="check a spec, the beat grid, and safe-area text fit")
    validate.add_argument("spec")
    validate.add_argument("-v", "--verbose", action="store_true")

    render = sub.add_parser("render", help="render one reel (the master, or a single variant)")
    _output_args(render)
    render.add_argument("--variant", default="master")

    batch = sub.add_parser("batch", help="render the master and every variant")
    _output_args(batch)

    args = parser.parse_args(argv)
    try:
        if args.cmd == "validate":
            return _validate(Path(args.spec), args.verbose)
        formats = _formats(args.formats)
        spec = load_spec(args.spec)
        if args.cmd == "render":
            spec = apply_variant(spec, args.variant)
            rendered = render_reel(spec, Path(args.out), formats, args.fps)
        else:
            rendered = render_batch(spec, Path(args.out), formats, args.fps)
    except SpecError as exc:
        print(exc, file=sys.stderr)
        return 2
    except TextFitError as exc:
        print(exc, file=sys.stderr)
        return 3
    except (AudioError, RuntimeError, OSError) as exc:
        print(exc, file=sys.stderr)
        return 1
    _print_rendered(rendered)
    return 0


def _output_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("spec")
    parser.add_argument("-o", "--out", required=True, help="directory for mp4 files")
    parser.add_argument("--formats", help="comma-separated subset, e.g. 9:16,1:1")
    parser.add_argument("--fps", type=int, default=None)


def _formats(value: str | None) -> list[str] | None:
    if not value:
        return None
    chosen = []
    for part in value.split(","):
        canonical = canonical_format(part)
        if canonical is None:
            raise SpecError([f"unknown format {part!r} (use 9:16, 4:5, or 1:1)"])
        if canonical not in chosen:
            chosen.append(canonical)
    return chosen


def _validate(path: Path, verbose: bool) -> int:
    spec = load_spec(path)
    jobs = [("master", spec)] + [(variant.id, apply_variant(spec, variant.id)) for variant in spec.variants]
    for _name, job in jobs:
        compiled = compile_reel(job)
        print(report(compiled, verbose))
    return 0


def _print_rendered(rendered: list) -> None:
    if not rendered:
        print("nothing rendered")
        return
    current = None
    for item in rendered:
        key = (item.variant, item.bpm, item.duration)
        if key != current:
            print(
                f"{item.path.parent.parent.name}  {item.variant}  "
                f"{item.bpm:.1f} bpm ({item.bpm_source})  {item.duration:.2f}s  "
                f"{item.lufs:.1f} LUFS  true peak {item.true_peak:.1f} dBTP"
            )
            current = key
        print(f"  wrote  {item.path}")


if __name__ == "__main__":
    raise SystemExit(main())
