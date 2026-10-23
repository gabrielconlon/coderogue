"""Language registry: every language the altars can speak.

Usage::

    from coderogue.languages import available, get

    lang = get("python")
    runtime = lang.detect()          # LanguageRuntime | None (cached)
    argv = lang.command(runtime, "main.py")

To add a language, write ``coderogue/languages/<name>.py`` with a :class:`Language` subclass
and add it to :func:`registry`.
"""

from __future__ import annotations

from coderogue.languages.base import (
    Language,
    LanguageRuntime,
    parse_version,
    parse_version_spec,
    version_matches,
)
from coderogue.languages.bash import BashLanguage
from coderogue.languages.powershell import PowerShellLanguage
from coderogue.languages.python import PythonLanguage

__all__ = [
    "LANGUAGE_IDS",
    "Language",
    "LanguageRuntime",
    "available",
    "get",
    "parse_version",
    "parse_version_spec",
    "registry",
    "version_matches",
]

#: Language ids accepted in puzzle files, in tab order.
LANGUAGE_IDS: tuple[str, ...] = ("python", "bash", "powershell")

_REGISTRY: dict[str, Language] | None = None


def registry() -> dict[str, Language]:
    """All known languages by id, in tab order (python, bash, powershell)."""
    global _REGISTRY
    if _REGISTRY is None:
        langs: list[Language] = [PythonLanguage(), BashLanguage(), PowerShellLanguage()]
        _REGISTRY = {lang.id: lang for lang in langs}
    return _REGISTRY


def get(language_id: str) -> Language:
    """Look up a language by id; raises ``KeyError`` for unknown ids."""
    return registry()[language_id]


def available() -> dict[str, Language]:
    """Languages whose interpreter was found on this machine."""
    return {lid: lang for lid, lang in registry().items() if lang.detect() is not None}
