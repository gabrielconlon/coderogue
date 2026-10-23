"""Tiny per-line syntax highlighter for the altar editor (pure Python, no pygame).

This is deliberately a line-at-a-time regex tokenizer: multi-line constructs such as Python
triple-quoted strings or bash heredocs are not tracked across lines.
"""

from __future__ import annotations

import re

Token = tuple[str, str]  # (text, kind)

KINDS = ("text", "keyword", "builtin", "string", "comment", "number", "variable")

PYTHON_KEYWORDS = frozenset(
    "False None True and as assert async await break class continue def del elif else except "
    "finally for from global if import in is lambda nonlocal not or pass raise return try "
    "while with yield match case".split()
)
PYTHON_BUILTINS = frozenset(
    "print input len range int str float bool list dict set tuple open sorted enumerate zip "
    "min max sum abs round type isinstance map filter reversed any all".split()
)
BASH_KEYWORDS = frozenset(
    "if then else elif fi for while until do done case esac in function select return break "
    "continue local export readonly declare".split()
)
BASH_BUILTINS = frozenset(
    "echo printf read cd pwd ls cat grep sed awk mkdir rm cp mv touch test exit source wc "
    "head tail sort uniq cut tr true false shift set unset".split()
)
POWERSHELL_KEYWORDS = frozenset(
    "if elseif else switch foreach for while do until break continue function return param "
    "begin process end try catch finally throw in -eq -ne -gt -ge -lt -le -like -match -and "
    "-or -not".split()
)

_PY = re.compile(
    r"""(?P<comment>\#.*)
    |(?P<string>[rRbBfFuU]{0,2}("([^"\\]|\\.)*"?|'([^'\\]|\\.)*'?))
    |(?P<number>\b\d[\d_]*(\.\d+)?\b)
    |(?P<word>[A-Za-z_]\w*)
    |(?P<other>\s+|.)""",
    re.VERBOSE,
)
_BASH = re.compile(
    r"""(?P<comment>(?<![\w$])\#.*)
    |(?P<string>"([^"\\]|\\.)*"?|'[^']*'?)
    |(?P<variable>\$\{[^}]*\}?|\$[A-Za-z_]\w*|\$[0-9#?@*$!])
    |(?P<number>\b\d+\b)
    |(?P<word>[A-Za-z_][\w-]*)
    |(?P<other>\s+|.)""",
    re.VERBOSE,
)
_PS = re.compile(
    r"""(?P<comment>\#.*)
    |(?P<string>"([^"`]|`.)*"?|'[^']*'?)
    |(?P<variable>\$[A-Za-z_]\w*(:\w+)?)
    |(?P<number>\b\d+(\.\d+)?\b)
    |(?P<word>-?[A-Za-z_][\w-]*)
    |(?P<other>\s+|.)""",
    re.VERBOSE,
)


def _classify_word(word: str, language: str) -> str:
    if language == "python":
        if word in PYTHON_KEYWORDS:
            return "keyword"
        return "builtin" if word in PYTHON_BUILTINS else "text"
    if language == "bash":
        if word in BASH_KEYWORDS:
            return "keyword"
        return "builtin" if word in BASH_BUILTINS else "text"
    lower = word.lower()
    if lower in POWERSHELL_KEYWORDS:
        return "keyword"
    if re.fullmatch(r"[A-Za-z]+-[A-Za-z]+", word):
        return "builtin"  # Verb-Noun cmdlet
    return "text"


def tokenize_line(line: str, language: str | None) -> list[Token]:
    """Split one line into ``(text, kind)`` tokens; kinds are listed in :data:`KINDS`.

    Unknown or ``None`` languages produce a single ``"text"`` token. Adjacent tokens of the
    same kind are merged, so concatenating all texts always reproduces ``line``.
    """
    if not line:
        return []
    pattern = {"python": _PY, "bash": _BASH, "powershell": _PS}.get(language or "")
    if pattern is None or language is None:
        return [(line, "text")]
    out: list[Token] = []
    for m in pattern.finditer(line):
        group = m.lastgroup or "other"
        text = m.group(0)
        if group == "word":
            kind = _classify_word(text, language)
        elif group == "other":
            kind = "text"
        else:
            kind = group
        if out and out[-1][1] == kind:
            out[-1] = (out[-1][0] + text, kind)
        else:
            out.append((text, kind))
    return out
