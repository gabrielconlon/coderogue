"""Quests from ``content/quests.yaml``: ordered steps, each finished by a story flag.

File format::

    - id: prologue
      title: "Prologue: Little Tilde"
      starts_when: null          # optional flag; the quest is hidden until it is set
      steps:
        - {text: "Fetch ink from the shelf.", done_when: got_ink}
"""

from __future__ import annotations

from collections.abc import Collection
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml


@dataclass(frozen=True)
class QuestStep:
    """One step; complete once ``done_when`` is in the flags."""

    text: str
    done_when: str


@dataclass(frozen=True)
class Quest:
    """A titled list of steps."""

    id: str
    title: str
    steps: tuple[QuestStep, ...]
    starts_when: str | None = None

    def started(self, flags: Collection[str]) -> bool:
        """True if the quest has begun."""
        return self.starts_when is None or self.starts_when in flags

    def current_step(self, flags: Collection[str]) -> QuestStep | None:
        """First unfinished step, or None when the quest is complete."""
        for step in self.steps:
            if step.done_when not in flags:
                return step
        return None

    def done(self, flags: Collection[str]) -> bool:
        """True when every step is finished."""
        return self.current_step(flags) is None


def parse_quests(data: Any) -> list[Quest]:
    """Build quests from parsed YAML (a list, or ``{quests: [...]}``)."""
    if isinstance(data, dict):
        data = data.get("quests", [])
    if not isinstance(data, list):
        raise ValueError("quests.yaml must be a list of quests")
    quests = []
    for raw in data:
        steps = tuple(
            QuestStep(str(s["text"]), str(s["done_when"])) for s in raw.get("steps", [])
        )
        starts = raw.get("starts_when")
        quests.append(Quest(
            str(raw["id"]), str(raw.get("title", raw["id"])), steps,
            str(starts) if starts else None,
        ))
    return quests


def load_quests(path: str | Path | None = None) -> list[Quest]:
    """Load ``path`` (default: the bundled ``content/quests.yaml``)."""
    if path is None:
        from coderogue.app import resource_path

        path = resource_path("content", "quests.yaml")
    with Path(path).open(encoding="utf-8") as fh:
        return parse_quests(yaml.safe_load(fh))


class QuestLog:
    """Reads the current quest and step off the flags, for the HUD.

    ``flags`` is held by reference (e.g. ``game.progress.flags``), so it stays live.
    """

    def __init__(self, flags: Collection[str], quests: list[Quest] | None = None) -> None:
        self.flags = flags
        self.quests = quests if quests is not None else load_quests()

    def current(self) -> tuple[Quest, QuestStep] | None:
        """The first started, unfinished quest and its current step."""
        for quest in self.quests:
            if not quest.started(self.flags):
                continue
            step = quest.current_step(self.flags)
            if step is not None:
                return quest, step
        return None

    @property
    def current_quest(self) -> Quest | None:
        """Current quest, or None."""
        cur = self.current()
        return cur[0] if cur else None

    @property
    def current_step_text(self) -> str:
        """Current step's text, or ``""``."""
        cur = self.current()
        return cur[1].text if cur else ""

    def hud_text(self) -> str:
        """``"<title>: <step>"`` or ``""``."""
        cur = self.current()
        return f"{cur[0].title}: {cur[1].text}" if cur else ""
