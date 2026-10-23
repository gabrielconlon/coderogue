"""Shared pieces of the language layer: the runtime record, version specs, and the base class.

Each concrete language (python, bash, powershell) subclasses :class:`Language` and fills in
interpreter discovery (:meth:`Language._probe`), the command line, and Moth's error catalogue.
Nothing here imports pygame; the module is safe to use from tools and tests.
"""

from __future__ import annotations

import difflib
import re
import subprocess
from abc import ABC, abstractmethod
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field

Version = tuple[int, ...]

_SPEC_CLAUSE = re.compile(r"^\s*(>=|<=|==|!=|>|<)?\s*(\d+(?:\.\d+)*)\s*$")


@dataclass(frozen=True)
class LanguageRuntime:
    """A concrete interpreter found on this machine."""

    language_id: str
    executable: str
    version: Version
    version_text: str = ""

    @property
    def version_str(self) -> str:
        """Dotted version, e.g. ``"5.3.20"``."""
        return ".".join(str(p) for p in self.version)


def parse_version(text: str) -> Version | None:
    """Return the first dotted number in ``text`` as a tuple, e.g. ``"5.3.20(1)"`` -> (5, 3, 20)."""
    m = re.search(r"(\d+(?:\.\d+)+|\d+)", text)
    if not m:
        return None
    return tuple(int(p) for p in m.group(1).split("."))


def parse_version_spec(spec: str) -> list[tuple[str, Version]]:
    """Parse ``">=4"`` or ``">=3.2, <6"`` into ``[(op, version), ...]``.

    A bare version (``"4"``) means ``>=4``. Raises ``ValueError`` on anything unparseable.
    """
    clauses: list[tuple[str, Version]] = []
    for part in str(spec).split(","):
        m = _SPEC_CLAUSE.match(part)
        if not m:
            raise ValueError(f"unparseable version spec {spec!r} (try something like '>=4')")
        op = m.group(1) or ">="
        clauses.append((op, tuple(int(p) for p in m.group(2).split("."))))
    if not clauses:
        raise ValueError(f"empty version spec {spec!r}")
    return clauses


def _cmp(a: Version, b: Version) -> int:
    width = max(len(a), len(b))
    pa = a + (0,) * (width - len(a))
    pb = b + (0,) * (width - len(b))
    return (pa > pb) - (pa < pb)


def version_matches(version: Version, spec: str) -> bool:
    """True if ``version`` satisfies every clause of ``spec``."""
    checks: dict[str, Callable[[int], bool]] = {
        ">=": lambda c: c >= 0,
        "<=": lambda c: c <= 0,
        ">": lambda c: c > 0,
        "<": lambda c: c < 0,
        "==": lambda c: c == 0,
        "!=": lambda c: c != 0,
    }
    return all(checks[op](_cmp(version, want)) for op, want in parse_version_spec(spec))


def run_probe(argv: Sequence[str], timeout: float = 5.0) -> str | None:
    """Run a short probe command and return stdout+stderr, or ``None`` if it could not run."""
    try:
        cp = subprocess.run(
            list(argv),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            stdin=subprocess.DEVNULL,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if cp.returncode != 0:
        return None
    return (cp.stdout or "") + (cp.stderr or "")


def suggest(word: str, candidates: Iterable[str]) -> str | None:
    """Closest known word to ``word`` (for "a typo of `print`?"), or ``None``."""
    matches = difflib.get_close_matches(word, list(candidates), n=1, cutoff=0.7)
    return matches[0] if matches else None


RuleBuilder = Callable[[re.Match[str], int | None], str]


@dataclass(frozen=True)
class ErrorRule:
    """One catalogue entry: a regex over stderr and a function building Moth's sentence.

    The builder gets the match and the line number found elsewhere in stderr (or ``None``).
    """

    pattern: re.Pattern[str]
    build: RuleBuilder


def at_line(line: int | None, fallback: str = "Your spell") -> str:
    """``"Line 3"`` or a fallback subject when the line is unknown."""
    return f"Line {line}" if line is not None else fallback


@dataclass
class Language(ABC):
    """A language the altar can run. Subclasses provide discovery, commands and errors."""

    id: str
    display_name: str
    file_name: str
    highlight_keywords: frozenset[str] = frozenset()
    #: Encoding used when the sandbox writes the player's script to disk.
    script_encoding: str = "utf-8"
    #: Extra seconds added to each test's timeout to cover slow interpreter start-up.
    startup_allowance_s: float = 0.0
    #: POSIX RLIMIT_NOFILE for a run, or None for the sandbox default (64). .NET needs more.
    max_open_files: int | None = None
    _cache: LanguageRuntime | None = field(default=None, init=False, repr=False, compare=False)
    _probed: bool = field(default=False, init=False, repr=False, compare=False)

    # -- discovery ---------------------------------------------------------------------------
    def detect(self) -> LanguageRuntime | None:
        """Find an interpreter (cached after the first call)."""
        if not self._probed:
            self._cache = self._probe()
            self._probed = True
        return self._cache

    def refresh(self) -> LanguageRuntime | None:
        """Forget the cached probe and look again (e.g. after the player installs bash 5)."""
        self._probed = False
        return self.detect()

    @abstractmethod
    def _probe(self) -> LanguageRuntime | None:
        """Look for an interpreter; return ``None`` if there is none."""

    # -- running -----------------------------------------------------------------------------
    @abstractmethod
    def command(self, runtime: LanguageRuntime, script_path: str) -> list[str]:
        """argv that runs ``script_path`` with ``runtime``."""

    def version_satisfies(self, runtime: LanguageRuntime, spec: str) -> bool:
        """True if the runtime's version meets a spec like ``">=4"`` or ``">=3.2"``."""
        return version_matches(runtime.version, spec)

    # -- errors ------------------------------------------------------------------------------
    rules: tuple[ErrorRule, ...] = field(default=(), repr=False, compare=False)

    def error_line(self, stderr: str) -> int | None:
        """Line number in the player's script that the error points at, if any."""
        return None

    def translate_error(self, stderr: str) -> str | None:
        """Moth's plain-language reading of ``stderr``, or ``None`` if nothing matched."""
        if not stderr or not stderr.strip():
            return None
        line = self.error_line(stderr)
        for rule in self.rules:
            m = rule.pattern.search(stderr)
            if m:
                return rule.build(m, line)
        return None
