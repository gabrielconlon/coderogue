"""Python: interpreter discovery, command line and Moth's error catalogue."""

from __future__ import annotations

import builtins
import keyword
import os
import re
import shutil
import sys

from coderogue.languages.base import (
    ErrorRule,
    Language,
    LanguageRuntime,
    RuleBuilder,
    at_line,
    parse_version,
    run_probe,
    suggest,
)

_KNOWN_NAMES = sorted(set(dir(builtins)) | set(keyword.kwlist))


#: Oldest CPython the puzzles are written for; older interpreters on PATH are skipped.
MIN_PYTHON: tuple[int, ...] = (3, 10)

#: Where a bundled python-build-standalone install lives (``tools/fetch_runtime.py``).
RUNTIME_PARTS = ("runtime", "python")
_RUNTIME_BINS = ("python.exe", "bin/python3", "bin/python")


def is_frozen() -> bool:
    """True inside a PyInstaller build, where ``sys.executable`` is the game itself."""
    return bool(getattr(sys, "frozen", False))


def bundled_python() -> str | None:
    """The interpreter shipped next to the game under ``runtime/python/``, if present."""
    from coderogue.app import resource_path

    base = resource_path(*RUNTIME_PARTS)
    for rel in _RUNTIME_BINS:
        cand = base / rel
        if cand.is_file() and os.access(cand, os.X_OK):
            return str(cand)
    return None


def _clt_missing() -> bool:
    """macOS: ``/usr/bin/python3`` is a stub that pops an installer unless the CLT exist."""
    if sys.platform != "darwin":
        return False
    return run_probe(["/usr/bin/xcode-select", "-p"]) is None


def _path_candidates() -> list[str]:
    """Every ``python3``/``python`` on PATH, then in common install dirs a GUI app's PATH
    lacks. All matches are returned (not just the first) so an old ``/usr/bin/python3``
    does not hide a newer Homebrew one."""
    dirs = os.environ.get("PATH", os.defpath).split(os.pathsep)
    if sys.platform == "darwin":
        dirs += ["/opt/homebrew/bin", "/usr/local/bin"]
    elif sys.platform.startswith("linux"):
        dirs += ["/usr/local/bin", "/usr/bin"]
    found: list[str] = []
    for d in dict.fromkeys(d for d in dirs if d):
        for name in ("python3", "python"):
            exe = shutil.which(name, path=d)
            if not exe or exe in found:
                continue
            if exe == "/usr/bin/python3" and _clt_missing():
                continue
            found.append(exe)
    return found


def _probe_exe(exe: str, language_id: str) -> LanguageRuntime | None:
    out = run_probe([exe, "--version"])
    version = parse_version(out) if out else None
    if not out or not version or version < MIN_PYTHON:
        return None
    return LanguageRuntime(language_id, exe, version, out.strip())


def _name_error(m: re.Match[str], line: int | None) -> str:
    name = m.group(1)
    guess = m.group(2) or suggest(name, _KNOWN_NAMES)
    text = f"{at_line(line)} mentions `{name}`, but nothing by that name exists yet."
    if guess and guess != name:
        text += f" A typo of `{guess}`?"
    else:
        text += " Is it spelled the same everywhere, and created before it is used?"
    return text


def _r(pattern: str, build: RuleBuilder) -> ErrorRule:
    return ErrorRule(re.compile(pattern, re.MULTILINE), build)


PYTHON_RULES: tuple[ErrorRule, ...] = (
    _r(
        r"^NameError: name '([^']+)' is not defined(?:\. Did you mean: '([^']+)'\?)?",
        _name_error,
    ),
    _r(
        r"^SyntaxError: unterminated (?:triple-quoted )?string literal",
        lambda m, ln: f"{at_line(ln)} opens a quote but never closes it. "
        "Every \" needs a partner at the end of the words.",
    ),
    _r(
        r"^SyntaxError: '([(\[{])' was never closed",
        lambda m, ln: f"{at_line(ln)} opens a `{m.group(1)}` that never closes. "
        "Count the brackets: each opener needs its closer.",
    ),
    _r(
        r"^SyntaxError: expected ':'",
        lambda m, ln: f"{at_line(ln)} starts a block (if, for, while, def...) "
        "and needs a colon `:` at the end.",
    ),
    _r(
        r"^IndentationError: expected an indented block",
        lambda m, ln: f"{at_line(ln)} should be indented: the line before it ends with `:` "
        "and opens a block. Add four spaces at the start.",
    ),
    _r(
        r"^IndentationError: unexpected indent",
        lambda m, ln: f"{at_line(ln)} starts with spaces it should not have. "
        "Remove the extra indentation.",
    ),
    _r(
        r"^(?:IndentationError|TabError): (?:unindent does not match|inconsistent use)",
        lambda m, ln: f"{at_line(ln)} is indented by a different amount than its neighbours. "
        "Line it up with the block it belongs to.",
    ),
    _r(
        r"^SyntaxError: invalid syntax\. Perhaps you forgot a comma\?",
        lambda m, ln: f"{at_line(ln)} has two things side by side with nothing joining them. "
        "A missing comma, or a missing `+`?",
    ),
    _r(
        r"^SyntaxError: ",
        lambda m, ln: f"The Terminal could not read {at_line(ln, 'your spell').lower()}. "
        "Look for a missing quote, bracket or symbol there.",
    ),
    _r(
        r"^ZeroDivisionError",
        lambda m, ln: f"{at_line(ln)} divides by zero, and nothing can be shared among "
        "zero baskets.",
    ),
    _r(
        r"^ValueError: invalid literal for int\(\) with base 10: (.*)$",
        lambda m, ln: f"{at_line(ln)} asked int() to turn {m.group(1)} into a number, "
        "but it is not a whole number.",
    ),
    _r(
        r"^TypeError: can only concatenate str \(not \"(\w+)\"\) to str",
        lambda m, ln: f"{at_line(ln)} glues words to a {m.group(1)} with `+`. "
        "Turn it into text first with str(...), or use an f-string.",
    ),
    _r(
        r"^TypeError: unsupported operand type\(s\) for (\S+): '(\w+)' and '(\w+)'",
        lambda m, ln: f"{at_line(ln)} uses `{m.group(1)}` on a {m.group(2)} and a "
        f"{m.group(3)}, which do not mix. Convert one of them first.",
    ),
    _r(
        r"^EOFError: EOF when reading a line",
        lambda m, ln: f"{at_line(ln)} waited for a line with input(), but no more lines came. "
        "Does the spell read more times than the ferryman speaks?",
    ),
    _r(
        r"^IndexError: list index out of range",
        lambda m, ln: f"{at_line(ln)} reaches past the end of a list. "
        "Remember the first item is number 0.",
    ),
    _r(
        r"^KeyError: (.*)$",
        lambda m, ln: f"{at_line(ln)} looks up {m.group(1)} in a dictionary that has "
        "no such key.",
    ),
    _r(
        r"^FileNotFoundError: .*No such file or directory: (.*)$",
        lambda m, ln: f"{at_line(ln)} opens {m.group(1)}, but no such file exists here. "
        "Check the spelling of the name.",
    ),
)


class PythonLanguage(Language):
    """CPython. The game's own interpreter in development; when frozen, the bundled runtime,
    otherwise ``python3`` from PATH."""

    def __init__(self) -> None:
        super().__init__(
            id="python",
            display_name="Python",
            file_name="main.py",
            highlight_keywords=frozenset(keyword.kwlist)
            | frozenset({"print", "input", "int", "str", "len", "range", "open"}),
            rules=PYTHON_RULES,
        )

    def _probe(self) -> LanguageRuntime | None:
        """In development: the game's own interpreter. Frozen (where ``sys.executable`` is
        the game): the bundled runtime, then ``python3``/``python`` on PATH (>= 3.10), else
        ``None`` so the Python tab is greyed out."""
        if not is_frozen():
            v = tuple(sys.version_info[:3])
            return LanguageRuntime(self.id, sys.executable, v, sys.version.split()[0])
        bundled = bundled_python()
        for exe in ([bundled] if bundled else []) + _path_candidates():
            rt = _probe_exe(exe, self.id)
            if rt:
                return rt
        return None

    def command(self, runtime: LanguageRuntime, script_path: str) -> list[str]:
        # -I isolated (ignores PYTHON* env and user site), -S no site, -B no .pyc files,
        # -X utf8 so stdout is UTF-8 everywhere (PYTHONIOENCODING is ignored under -I).
        return [runtime.executable, "-I", "-S", "-B", "-X", "utf8", script_path]

    def error_line(self, stderr: str) -> int | None:
        hits = re.findall(rf'File "(?:[^"]*[\\/])?{re.escape(self.file_name)}", line (\d+)', stderr)
        return int(hits[-1]) if hits else None
