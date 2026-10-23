"""Generate the hand-drawn sprites committed under ``assets/sprites/`` (deterministic).

Usage::

    python tools/gen_sprites.py            # (re)write every sprite sheet
    python tools/gen_sprites.py --check    # exit 1 if a committed sheet differs

Sprites are drawn pixel by pixel from the ASCII art below, in the Kenney Tiny Dungeon
palette and outline style (dark 1 px outline, flat fills, a top-left highlight). Each sheet
is a horizontal strip of 16x16 frames on a transparent background.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")

import pygame  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parent.parent
SPRITES_DIR = REPO_ROOT / "assets" / "sprites"
FRAME = 16

Color = tuple[int, int, int, int]

MOTH_PALETTE: dict[str, Color] = {
    "O": (28, 24, 34, 255),  # outline
    "W": (214, 180, 120, 255),  # wings
    "H": (240, 218, 170, 255),  # wing highlight (top-left light)
    "B": (120, 86, 60, 255),  # body
}

# Frame 1: wings spread. Frame 2: wings raised. The moth faces left (like Kenney heroes):
# the highlight sits on the left wing, so a flipped sprite reads as facing right.
MOTH_FRAMES: tuple[tuple[str, ...], ...] = (
    (
        "................",
        "....O......O....",
        ".....O....O.....",
        "......OOOO......",
        "..OOO.OBBO.OOO..",
        ".OHHWOOBBOOWWWO.",
        ".OHWWWOBBOWWWWO.",
        ".OHWWWOBBOWWWWO.",
        "..OWWWOBBOWWWO..",
        "..OWWOOBBOOWWO..",
        "...OWWOBBOWWO...",
        "....OOOBBOOO....",
        "......OBBO......",
        ".......OO.......",
        "................",
        "................",
    ),
    (
        "................",
        "....O......O....",
        ".OO..O....O..OO.",
        ".OHO..OOOO..OWO.",
        ".OHWO.OBBO.OWWO.",
        ".OHWWOOBBOOWWWO.",
        "..OHWWOBBOWWWO..",
        "..OWWWOBBOWWWO..",
        "...OWWOBBOWWO...",
        "....OOOBBOOO....",
        "......OBBO......",
        "......OBBO......",
        ".......OO.......",
        "................",
        "................",
        "................",
    ),
)

SHEETS: dict[str, tuple[tuple[tuple[str, ...], ...], dict[str, Color]]] = {
    "moth.png": (MOTH_FRAMES, MOTH_PALETTE),
}


def render_sheet(
    frames: tuple[tuple[str, ...], ...], palette: dict[str, Color]
) -> pygame.Surface:
    """A ``16 * len(frames)`` x 16 transparent strip with each ASCII frame painted in."""
    sheet = pygame.Surface((FRAME * len(frames), FRAME), pygame.SRCALPHA)
    sheet.fill((0, 0, 0, 0))
    for i, rows in enumerate(frames):
        if len(rows) != FRAME or any(len(r) != FRAME for r in rows):
            raise ValueError(f"frame {i} must be {FRAME}x{FRAME}")
        for y, row in enumerate(rows):
            for x, ch in enumerate(row):
                if ch != ".":
                    sheet.set_at((i * FRAME + x, y), palette[ch])
    return sheet


def _pixels(surf: pygame.Surface) -> bytes:
    return pygame.image.tobytes(surf, "RGBA")


def main(argv: list[str] | None = None) -> int:
    """CLI entry point."""
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--check", action="store_true", help="diff against committed PNGs")
    args = parser.parse_args(argv)
    SPRITES_DIR.mkdir(parents=True, exist_ok=True)
    stale = []
    for name, (frames, palette) in SHEETS.items():
        sheet = render_sheet(frames, palette)
        out = SPRITES_DIR / name
        if args.check:
            if not out.exists() or _pixels(pygame.image.load(str(out))) != _pixels(sheet):
                stale.append(out)
            continue
        pygame.image.save(sheet, str(out))
        print(f"wrote {out}")
    for path in stale:
        print(f"{path} is stale (run tools/gen_sprites.py)", file=sys.stderr)
    return 1 if stale else 0


if __name__ == "__main__":
    raise SystemExit(main())
