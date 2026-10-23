"""Data-driven dialogue loaded from ``content/dialogue/<area>.yaml``.

Each file is a mapping of dialogue id to an entry::

    pell_intro:
      npc: pell              # which NPC key this belongs to (for DialogueBank.pick)
      speaker: Pell          # name shown in the panel
      once: false            # once: true -> skipped after it has played ("seen:<id>")
      requires: [flag, ...]  # all must be set
      unless: [flag, ...]    # none may be set (optional)
      sets: [flag, ...]      # set when the dialogue finishes
      lines: ["...", "..."]
      choices:               # optional, shown after the last line
        - {text: "Fine.", sets: [wren_fine]}

For :meth:`DialogueBank.pick`, entries are tried in file order and the first eligible one
wins, so put later-chapter lines first with stricter ``requires``.
"""

from __future__ import annotations

from collections.abc import Collection
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from coderogue.story.flags import has_all, has_any


class DialogueError(ValueError):
    """A dialogue file is malformed."""


@dataclass(frozen=True)
class Choice:
    """One reply option."""

    text: str
    sets: tuple[str, ...] = ()


@dataclass(frozen=True)
class Dialogue:
    """One conversation: a speaker, some lines and optional choices."""

    id: str
    speaker: str
    lines: tuple[str, ...]
    npc: str = ""
    once: bool = False
    requires: tuple[str, ...] = ()
    unless: tuple[str, ...] = ()
    sets: tuple[str, ...] = ()
    choices: tuple[Choice, ...] = ()

    @property
    def seen_flag(self) -> str:
        """Flag recorded when a ``once`` dialogue has played."""
        return f"seen:{self.id}"

    def eligible(self, flags: Collection[str]) -> bool:
        """True if ``requires``/``unless``/``once`` allow this dialogue now."""
        if self.once and self.seen_flag in flags:
            return False
        return has_all(flags, self.requires) and not has_any(flags, self.unless)

    def flags_on_finish(self, choice: Choice | None = None) -> list[str]:
        """Flags to set when the dialogue ends (with the picked ``choice``, if any)."""
        out = list(self.sets)
        if choice is not None:
            out += choice.sets
        if self.once:
            out.append(self.seen_flag)
        return out


def _str_list(value: Any, where: str) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        return (value,)
    if not isinstance(value, list):
        raise DialogueError(f"{where}: expected a list of strings")
    return tuple(str(v) for v in value)


def parse_dialogue(did: str, raw: Any, source: str = "<data>") -> Dialogue:
    """Build a :class:`Dialogue` from one YAML entry."""
    where = f"{source}:{did}"
    if not isinstance(raw, dict):
        raise DialogueError(f"{where}: entry must be a mapping")
    lines = _str_list(raw.get("lines"), f"{where}.lines")
    if not lines:
        raise DialogueError(f"{where}: needs at least one line")
    choices = []
    for i, c in enumerate(raw.get("choices") or []):
        if isinstance(c, str):
            choices.append(Choice(c))
        elif isinstance(c, dict) and "text" in c:
            choices.append(Choice(str(c["text"]), _str_list(c.get("sets"), f"{where}.c{i}")))
        else:
            raise DialogueError(f"{where}: choice {i} needs a 'text'")
    return Dialogue(
        id=str(did),
        speaker=str(raw.get("speaker", "")),
        lines=lines,
        npc=str(raw.get("npc", "")),
        once=bool(raw.get("once", False)),
        requires=_str_list(raw.get("requires"), f"{where}.requires"),
        unless=_str_list(raw.get("unless"), f"{where}.unless"),
        sets=_str_list(raw.get("sets"), f"{where}.sets"),
        choices=tuple(choices),
    )


@dataclass
class DialogueBank:
    """All loaded dialogue, in load order."""

    entries: dict[str, Dialogue] = field(default_factory=dict)

    def add_mapping(self, data: Any, source: str = "<data>") -> None:
        """Add every entry of a parsed YAML mapping."""
        if data is None:
            return
        if not isinstance(data, dict):
            raise DialogueError(f"{source}: top level must be a mapping of id -> entry")
        for did, raw in data.items():
            if str(did) in self.entries:
                raise DialogueError(f"{source}: duplicate dialogue id {did!r}")
            self.entries[str(did)] = parse_dialogue(str(did), raw, source)

    def load_file(self, path: str | Path) -> None:
        """Add the entries of one YAML file."""
        path = Path(path)
        with path.open(encoding="utf-8") as fh:
            self.add_mapping(yaml.safe_load(fh), path.name)

    @classmethod
    def load_dir(cls, path: str | Path) -> DialogueBank:
        """Load every ``*.yaml``/``*.yml`` in ``path`` (sorted by name)."""
        bank = cls()
        directory = Path(path)
        if directory.is_dir():
            files = sorted([*directory.glob("*.yaml"), *directory.glob("*.yml")])
            for file in files:
                bank.load_file(file)
        return bank

    @classmethod
    def load_default(cls) -> DialogueBank:
        """Load ``content/dialogue`` from the game's resources."""
        from coderogue.app import resource_path

        return cls.load_dir(resource_path("content", "dialogue"))

    def get(self, did: str) -> Dialogue:
        """Dialogue by id (KeyError if missing)."""
        return self.entries[did]

    def for_npc(self, npc: str) -> list[Dialogue]:
        """All entries tagged ``npc: <npc>``, in file order."""
        return [d for d in self.entries.values() if d.npc == npc]

    def pick(self, npc: str, flags: Collection[str]) -> Dialogue | None:
        """First eligible entry for ``npc`` given ``flags``, or None."""
        for d in self.for_npc(npc):
            if d.eligible(flags):
                return d
        return None
