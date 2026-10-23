"""Player progress through the altars: solves, skips, hints, drafts, XP and story flags.

A plain dataclass with no IO. The save layer (``coderogue.save``) serializes it with
:meth:`Progress.to_dict` and restores it with :meth:`Progress.from_dict`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

XP_PER_LEVEL = 100
HINT_RUNGS = 3


def bilingual_flag(puzzle_id: str) -> str:
    """Flag set when ``puzzle_id`` has been solved in two or more languages."""
    return f"bilingual:{puzzle_id}"


@dataclass
class Progress:
    """Everything the altars remember about the player.

    ``hints_used`` is the highest hint rung viewed per puzzle (any language, for the journal);
    ``hint_rungs`` is the rung reached per ``(puzzle_id, language)`` so ``?`` resumes there.
    """

    solved: dict[str, set[str]] = field(default_factory=dict)
    skipped: set[str] = field(default_factory=set)
    hints_used: dict[str, int] = field(default_factory=dict)
    hint_rungs: dict[tuple[str, str], int] = field(default_factory=dict)
    drafts: dict[tuple[str, str], str] = field(default_factory=dict)
    xp: int = 0
    flags: set[str] = field(default_factory=set)

    # ---- queries ----------------------------------------------------------------------
    @property
    def level(self) -> int:
        """1-based level derived from XP."""
        return self.xp // XP_PER_LEVEL + 1

    @property
    def xp_into_level(self) -> int:
        """XP earned since the current level started."""
        return self.xp % XP_PER_LEVEL

    def is_solved(self, puzzle_id: str, language: str | None = None) -> bool:
        """True if ``puzzle_id`` is solved (in ``language``, or in any language)."""
        langs = self.solved.get(puzzle_id, set())
        return language in langs if language is not None else bool(langs)

    def is_bilingual(self, puzzle_id: str) -> bool:
        """True if ``puzzle_id`` has been solved in at least two languages."""
        return len(self.solved.get(puzzle_id, set())) >= 2

    def hint_rung(self, puzzle_id: str, language: str) -> int:
        """Highest hint rung (0-3) viewed for this puzzle in ``language``."""
        return self.hint_rungs.get((puzzle_id, language), 0)

    def draft(self, puzzle_id: str, language: str) -> str | None:
        """The saved editor text for this puzzle/language, if any."""
        return self.drafts.get((puzzle_id, language))

    # ---- updates ----------------------------------------------------------------------
    def mark_solved(self, puzzle_id: str, language: str, xp: int = 0) -> bool:
        """Record a solve. Awards ``xp`` on the puzzle's first solve in any language (half
        if it was skipped first). Returns True if this was the puzzle's first solve."""
        langs = self.solved.setdefault(puzzle_id, set())
        first = not langs
        langs.add(language)
        if first and xp:
            self.xp += xp // 2 if puzzle_id in self.skipped else xp
        if len(langs) >= 2:
            self.flags.add(bilingual_flag(puzzle_id))
        return first

    def mark_skipped(self, puzzle_id: str) -> None:
        """Record that the player skipped ``puzzle_id`` (the altar stays unlit)."""
        self.skipped.add(puzzle_id)

    def note_hint(self, puzzle_id: str, language: str, rung: int) -> None:
        """Remember that hint ``rung`` (1-3) was viewed."""
        rung = max(0, min(HINT_RUNGS, rung))
        key = (puzzle_id, language)
        self.hint_rungs[key] = max(self.hint_rungs.get(key, 0), rung)
        self.hints_used[puzzle_id] = max(self.hints_used.get(puzzle_id, 0), rung)

    def set_draft(self, puzzle_id: str, language: str, text: str) -> None:
        """Store the editor text for this puzzle/language."""
        self.drafts[(puzzle_id, language)] = text

    # ---- serialization ----------------------------------------------------------------
    def to_dict(self) -> dict[str, Any]:
        """JSON-safe dict (sets become sorted lists; tuple keys become nested dicts)."""
        hint_rungs: dict[str, dict[str, int]] = {}
        for (pid, lang), rung in sorted(self.hint_rungs.items()):
            hint_rungs.setdefault(pid, {})[lang] = rung
        drafts: dict[str, dict[str, str]] = {}
        for (pid, lang), text in sorted(self.drafts.items()):
            drafts.setdefault(pid, {})[lang] = text
        return {
            "solved": {pid: sorted(langs) for pid, langs in sorted(self.solved.items())},
            "skipped": sorted(self.skipped),
            "hints_used": dict(sorted(self.hints_used.items())),
            "hint_rungs": hint_rungs,
            "drafts": drafts,
            "xp": self.xp,
            "flags": sorted(self.flags),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> Progress:
        """Inverse of :meth:`to_dict`; missing keys take their defaults."""
        data = data or {}
        hint_rungs = {
            (str(pid), str(lang)): int(rung)
            for pid, langs in (data.get("hint_rungs") or {}).items()
            for lang, rung in langs.items()
        }
        drafts = {
            (str(pid), str(lang)): str(text)
            for pid, langs in (data.get("drafts") or {}).items()
            for lang, text in langs.items()
        }
        return cls(
            solved={str(k): set(map(str, v)) for k, v in (data.get("solved") or {}).items()},
            skipped=set(map(str, data.get("skipped") or ())),
            hints_used={str(k): int(v) for k, v in (data.get("hints_used") or {}).items()},
            hint_rungs=hint_rungs,
            drafts=drafts,
            xp=int(data.get("xp", 0)),
            flags=set(map(str, data.get("flags") or ())),
        )
