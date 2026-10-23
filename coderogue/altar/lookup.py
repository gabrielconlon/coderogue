"""Find the puzzle an altar refers to, and cache the loaded puzzle specs on the game."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from coderogue.puzzles import PuzzleSpec

# Curriculum ids from docs/DESIGN.md: "P-01" (Prologue), "1-05", "2-B" (boss).
_CURRICULUM_ID = re.compile(r"^(?:ch)?(P|\d+)-(\d+|B)$", re.IGNORECASE)


def resolve_puzzle_id(puzzles: dict[str, PuzzleSpec], ref: str) -> str | None:
    """The spec id for an altar's ``puzzle`` reference, or None if nothing matches.

    Accepts the spec id itself (``ch0-01``) or a curriculum id (``P-01``, ``1-05``, ``1-B``),
    which is matched by chapter and order (``B`` = that chapter's boss).
    """
    ref = ref.strip()
    if ref in puzzles:
        return ref
    m = _CURRICULUM_ID.match(ref)
    if m is None:
        return None
    chapter = 0 if m.group(1).upper() == "P" else int(m.group(1))
    order = m.group(2).upper()
    for pid, spec in sorted(puzzles.items()):
        if spec.chapter != chapter:
            continue
        if order == "B" and spec.is_boss:
            return pid
        if order != "B" and spec.order == int(order):
            return pid
    return None


def game_puzzles(game: Any) -> dict[str, PuzzleSpec]:
    """All puzzle specs, loaded once from ``content/puzzles`` and cached as ``game.puzzles``."""
    puzzles = getattr(game, "puzzles", None)
    if not puzzles:
        from coderogue.app import resource_path
        from coderogue.puzzles import load_all

        puzzles = load_all(resource_path("content", "puzzles"))
        try:
            game.puzzles = puzzles
        except AttributeError:  # pragma: no cover - read-only stand-in game objects
            pass
    return puzzles
