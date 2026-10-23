"""bash: interpreter discovery, command line and Moth's error catalogue.

Content is written to run on bash 3.2 (stock macOS) unless a puzzle says ``requires: {bash:
">=4"}``. Discovery prefers a Homebrew bash because it is newer.
"""

from __future__ import annotations

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

_COMMON_COMMANDS = (
    "echo printf read if then else elif fi for while until do done case esac function "
    "local return exit test cat grep sort uniq wc head tail cut tr sed awk ls cd pwd "
    "mkdir touch rm cp mv true false declare let export"
).split()

BASH_KEYWORDS = frozenset(
    "if then else elif fi for in while until do done case esac function select time "
    "echo printf read local return exit declare export test let shift break continue".split()
)


def _command_not_found(m: re.Match[str], line: int | None) -> str:
    cmd = m.group(1)
    guess = suggest(cmd, _COMMON_COMMANDS)
    text = f"{at_line(line)} calls `{cmd}`, but no command has that name."
    if guess and guess != cmd:
        text += f" A typo of `{guess}`?"
    return text


def _unexpected_token(m: re.Match[str], line: int | None) -> str:
    tok = m.group(1)
    where = at_line(line, "The spell")
    if tok == "fi":
        return f"bash reached `fi` without a `then` ({where.lower()}). Every `if` needs `; then`."
    if tok == "done":
        return f"bash reached `done` without a `do` ({where.lower()}). Loops need `; do`."
    if tok in {"else", "elif"}:
        return f"bash found `{tok}` on {where.lower()} without an `if ...; then` before it."
    return f"bash did not expect `{tok}` on {where.lower()}. Check the line just before it too."


def _r(pattern: str, build: RuleBuilder) -> ErrorRule:
    return ErrorRule(re.compile(pattern, re.MULTILINE), build)


BASH_RULES: tuple[ErrorRule, ...] = (
    _r(r": ([^:\n]+): command not found", _command_not_found),
    _r(
        r"unexpected EOF while looking for matching [`'](.)'",
        lambda m, ln: f"{at_line(ln, 'A line')} opens a {m.group(1)} quote that never closes. "
        "Every opening quote needs a partner.",
    ),
    _r(r"syntax error near unexpected token [`']([^'\n]*)'", _unexpected_token),
    _r(
        r"syntax error: unexpected end of file",
        lambda m, ln: "The spell ended while bash was still waiting for something to close: "
        "an `if` needs `fi`, a loop needs `done`, a `{` needs `}`.",
    ),
    _r(
        r"\[: ([^:\n]*): integer (?:expression )?expected",
        lambda m, ln: (
            f"The `[` test on {at_line(ln, 'one line').lower()} expected a number but got "
            + ("an empty value. Is the variable spelled the same everywhere?"
               if not m.group(1).strip() else f"`{m.group(1)}`.")
        ),
    ),
    _r(
        r": ([A-Za-z_]\w*): unbound variable",
        lambda m, ln: f"{at_line(ln)} uses `${m.group(1)}`, but nothing was ever stored in it. "
        "A typo, or a variable set too late?",
    ),
    _r(
        r"division by 0",
        lambda m, ln: f"{at_line(ln)} divides by zero inside `$(( ))`.",
    ),
    _r(
        r"syntax error: operand expected",
        lambda m, ln: f"The arithmetic on {at_line(ln, 'one line').lower()} is missing a number. "
        "Is a variable empty or misspelled?",
    ),
    _r(
        r"\[: too many arguments",
        lambda m, ln: f"The `[` test on {at_line(ln, 'one line').lower()} got too many words. "
        "Put double quotes around the variable: \"$name\".",
    ),
    _r(
        r"\[: [^:\n]*: unary operator expected",
        lambda m, ln: f"The `[` test on {at_line(ln, 'one line').lower()} has an empty side. "
        "Quote the variable (\"$x\") so an empty value still counts.",
    ),
    _r(
        r": (\$\{[^}]*\}): bad substitution",
        lambda m, ln: f"{at_line(ln)} uses `{m.group(1)}`, which this bash does not understand. "
        "Older bash (3.2 on macOS) lacks some newer tricks.",
    ),
    _r(
        r"(?:^|: )([^:\n]+): No such file or directory",
        lambda m, ln: f"`{m.group(1).strip()}` does not exist here. Check the file's name.",
    ),
)


def _bash_candidates() -> list[str]:
    if sys.platform == "win32":
        # Only accept a bash the player already put on PATH (Git Bash or WSL).
        found = shutil.which("bash")
        return [found] if found else []
    cands = ["/opt/homebrew/bin/bash", "/usr/local/bin/bash"]
    found = shutil.which("bash")
    if found:
        cands.append(found)
    cands.append("/bin/bash")
    seen: list[str] = []
    for c in cands:
        if c not in seen and os.path.isfile(c) and os.access(c, os.X_OK):
            seen.append(c)
    return seen


class BashLanguage(Language):
    """GNU bash, 3.2 or newer."""

    def __init__(self) -> None:
        super().__init__(
            id="bash",
            display_name="bash",
            file_name="main.sh",
            highlight_keywords=BASH_KEYWORDS,
            rules=BASH_RULES,
        )

    def _probe(self) -> LanguageRuntime | None:
        for exe in _bash_candidates():
            out = run_probe([exe, "--version"])
            if not out:
                continue
            m = re.search(r"version (\d+(?:\.\d+)*)", out)
            version = parse_version(m.group(1)) if m else None
            if version:
                return LanguageRuntime(self.id, exe, version, out.splitlines()[0].strip())
        return None

    def command(self, runtime: LanguageRuntime, script_path: str) -> list[str]:
        return [runtime.executable, "--noprofile", "--norc", script_path]

    def error_line(self, stderr: str) -> int | None:
        hits = re.findall(rf"{re.escape(self.file_name)}: line (\d+):", stderr)
        return int(hits[0]) if hits else None
