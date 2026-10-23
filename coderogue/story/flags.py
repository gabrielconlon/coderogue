"""Story flags: a plain set of strings with a few helpers.

The game's source of truth is ``game.progress.flags`` (builder D's ``Progress``); these
helpers accept any set- or list-like collection so story code does not depend on it.

Conventions: ``met:<npc>``, ``seen:<dialogue id>`` (set automatically for ``once``
dialogue), ``solved:<puzzle id>``, plus beat flags such as ``null_came``.
"""

from __future__ import annotations

from collections.abc import Collection, Iterable
from typing import Any


class Flags(set[str]):
    """A set of story flags."""

    def has_all(self, names: Iterable[str]) -> bool:
        """True if every flag in ``names`` is set."""
        return all(n in self for n in names)

    def has_any(self, names: Iterable[str]) -> bool:
        """True if at least one flag in ``names`` is set."""
        return any(n in self for n in names)

    def set_all(self, names: Iterable[str]) -> None:
        """Set every flag in ``names``."""
        self.update(names)


def has_all(flags: Collection[str], names: Iterable[str]) -> bool:
    """True if every name is in ``flags``."""
    return all(n in flags for n in names)


def has_any(flags: Collection[str], names: Iterable[str]) -> bool:
    """True if any name is in ``flags``."""
    return any(n in flags for n in names)


def apply_flags(target: Any, names: Iterable[str]) -> None:
    """Add ``names`` to ``target`` whether it is a set (``add``) or a list (``append``)."""
    for name in names:
        if isinstance(target, set):
            target.add(name)
        elif name not in target:
            target.append(name)
