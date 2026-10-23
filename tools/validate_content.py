#!/usr/bin/env python3
"""Lint every puzzle under content/puzzles/: solutions must pass, starters must fail.

Usage::

    python tools/validate_content.py                 # lint with every installed language
    python tools/validate_content.py --list-missing  # show puzzles lacking a language variant
    python tools/validate_content.py --languages python bash

Languages whose interpreter is not installed (or is older than a puzzle's ``requires``) are
skipped with a note, so this runs on any CI runner. Exit status is non-zero if any file fails
to load or any reference check fails.
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from coderogue.languages import LANGUAGE_IDS, available, get  # noqa: E402
from coderogue.puzzles.runner import RunnerError, reference_check  # noqa: E402
from coderogue.puzzles.spec import PuzzleSpec, SpecError, load_puzzle, puzzle_files  # noqa: E402

DEFAULT_CONTENT = ROOT / "content" / "puzzles"


def _load(content_dir: Path) -> tuple[list[PuzzleSpec], list[str]]:
    specs: list[PuzzleSpec] = []
    errors: list[str] = []
    seen: dict[str, str] = {}
    for path in puzzle_files(content_dir):
        try:
            spec = load_puzzle(path)
        except SpecError as exc:
            errors.append(str(exc))
            continue
        if spec.id in seen:
            errors.append(f"{path}: duplicate id {spec.id!r} (also in {seen[spec.id]})")
            continue
        seen[spec.id] = str(path)
        specs.append(spec)
    return specs, errors


def _table(rows: list[tuple[str, ...]]) -> str:
    widths = [max(len(r[i]) for r in rows) for i in range(len(rows[0]))]
    lines = []
    for n, row in enumerate(rows):
        lines.append("  ".join(cell.ljust(w) for cell, w in zip(row, widths, strict=True)))
        if n == 0:
            lines.append("  ".join("-" * w for w in widths))
    return "\n".join(line.rstrip() for line in lines)


def main(argv: list[str] | None = None) -> int:
    """CLI entry point; returns the exit status."""
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--content-dir", type=Path, default=DEFAULT_CONTENT)
    ap.add_argument("--languages", nargs="*", choices=LANGUAGE_IDS,
                    help="only check these languages (default: all installed)")
    ap.add_argument("--list-missing", action="store_true",
                    help="list puzzles that lack a variant for some language, then exit")
    args = ap.parse_args(argv)

    specs, load_errors = _load(args.content_dir)
    for err in load_errors:
        print(f"LOAD ERROR {err}", file=sys.stderr)
    if not specs and not load_errors:
        print(f"no puzzles found under {args.content_dir}")
        return 1

    if args.list_missing:
        rows = [("puzzle", "missing languages")]
        for spec in specs:
            have = set(spec.language_ids())
            missing = [lid for lid in LANGUAGE_IDS if lid not in have]
            if missing:
                rows.append((spec.id, ", ".join(missing)))
        print(_table(rows) if len(rows) > 1 else "every puzzle has every language")
        return 1 if load_errors else 0

    wanted = args.languages or list(LANGUAGE_IDS)
    installed = available()
    for lid in wanted:
        if lid in installed:
            rt = installed[lid].detect()
            assert rt is not None
            print(f"{lid}: {rt.executable} ({rt.version_str})")
        else:
            print(f"{lid}: not installed here, skipping")

    rows: list[tuple[str, ...]] = [("puzzle", "language", "phase", "result", "detail")]
    failures = 0
    start = time.monotonic()
    for spec in specs:
        for lid in wanted:
            if lid not in spec.languages and not spec.phases:
                rows.append((spec.id, lid, "-", "missing", "no variant (see --list-missing)"))
                continue
            if lid not in installed:
                rows.append((spec.id, lid, "-", "skip", f"{get(lid).display_name} not installed"))
                continue
            try:
                reports = reference_check(spec, lid)
            except RunnerError as exc:
                rows.append((spec.id, lid, "-", "skip", str(exc)))
                continue
            for rep in reports:
                phase = "-" if rep.phase is None else str(rep.phase)
                if rep.ok:
                    rows.append((spec.id, lid, phase, "ok", ""))
                else:
                    failures += 1
                    rows.append((spec.id, lid, phase, "FAIL", " | ".join(rep.problems)))
    print()
    print(_table(rows))
    print(f"\n{len(specs)} puzzle(s), {failures} failure(s), {len(load_errors)} load error(s) "
          f"in {time.monotonic() - start:.1f}s")
    return 1 if failures or load_errors else 0


if __name__ == "__main__":
    sys.exit(main())
