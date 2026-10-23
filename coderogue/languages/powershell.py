"""PowerShell: discovery (pwsh first, then Windows PowerShell), command line and errors.

PowerShell is optional. When neither ``pwsh`` nor ``powershell.exe`` is on PATH, ``detect()``
returns ``None`` and the altar simply does not offer the PowerShell tab.
"""

from __future__ import annotations

import re
import shutil

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

_COMMON_CMDLETS = (
    "Write-Output Write-Host Read-Host Get-Content Set-Content Add-Content Out-File "
    "ForEach-Object Where-Object Sort-Object Measure-Object Select-Object Get-ChildItem "
    "Test-Path New-Item Remove-Item"
).split()

PS_KEYWORDS = frozenset(
    "if else elseif switch foreach for while do until function param return break continue "
    "begin process end in Write-Output Write-Host Read-Host".split()
)


def _not_recognized(m: re.Match[str], line: int | None) -> str:
    name = m.group(1)
    guess = suggest(name, _COMMON_CMDLETS)
    text = f"{at_line(line)} calls `{name}`, but PowerShell knows no command by that name."
    if guess and guess != name:
        text += f" A typo of `{guess}`?"
    return text


def _r(pattern: str, build: RuleBuilder) -> ErrorRule:
    return ErrorRule(re.compile(pattern, re.MULTILINE | re.IGNORECASE), build)


PS_RULES: tuple[ErrorRule, ...] = (
    _r(r"The term '([^']+)' is not recognized", _not_recognized),
    _r(
        r"string is missing the terminator",
        lambda m, ln: f"{at_line(ln, 'A line')} opens a quote that never closes.",
    ),
    _r(
        r"Missing closing '([)}\]])'",
        lambda m, ln: f"{at_line(ln, 'A block')} is missing its closing `{m.group(1)}`.",
    ),
    _r(
        r"Missing expression after",
        lambda m, ln: f"{at_line(ln)} has an operator with nothing after it.",
    ),
    _r(
        r"Unexpected token '([^']*)'",
        lambda m, ln: f"PowerShell did not expect `{m.group(1)}` on "
        f"{at_line(ln, 'one line').lower()}. A missing quote or operator nearby?",
    ),
    _r(
        r"Attempted to divide by zero",
        lambda m, ln: f"{at_line(ln)} divides by zero.",
    ),
    _r(
        r"Cannot convert value \"([^\"]*)\" to type \"System\.Int",
        lambda m, ln: f"{at_line(ln)} tried to turn \"{m.group(1)}\" into a number, "
        "but it is not a whole number.",
    ),
    _r(
        r"You cannot call a method on a null-valued expression",
        lambda m, ln: f"{at_line(ln)} calls a method on something empty. "
        "Was the variable set, and spelled the same?",
    ),
    _r(
        r"The variable '\$?([^']+)' cannot be retrieved because it has not been set",
        lambda m, ln: f"{at_line(ln)} uses `${m.group(1)}` before anything was stored in it.",
    ),
    _r(
        r"Cannot find path '([^']+)'",
        lambda m, ln: f"{at_line(ln)} looks for `{m.group(1)}`, which does not exist here.",
    ),
    _r(
        r"Index was outside the bounds of the array",
        lambda m, ln: f"{at_line(ln)} reaches past the end of an array. "
        "The first item is number 0.",
    ),
)


class PowerShellLanguage(Language):
    """PowerShell 7 (``pwsh``) or Windows PowerShell 5.1 (``powershell.exe``)."""

    def __init__(self) -> None:
        super().__init__(
            id="powershell",
            display_name="PowerShell",
            file_name="main.ps1",
            highlight_keywords=PS_KEYWORDS,
            # Windows PowerShell 5.1 reads BOM-less scripts as ANSI; a BOM keeps UTF-8 intact.
            script_encoding="utf-8-sig",
            startup_allowance_s=2.0,
            rules=PS_RULES,
        )

    def _probe(self) -> LanguageRuntime | None:
        for name in ("pwsh", "powershell.exe", "powershell"):
            exe = shutil.which(name)
            if not exe:
                continue
            out = run_probe(
                [exe, "-NoProfile", "-NonInteractive", "-Command",
                 "$PSVersionTable.PSVersion.ToString()"],
                timeout=15.0,
            )
            version = parse_version(out) if out else None
            if version:
                return LanguageRuntime(self.id, exe, version, out.strip() if out else "")
        return None

    def command(self, runtime: LanguageRuntime, script_path: str) -> list[str]:
        return [
            runtime.executable,
            "-NoProfile",
            "-NonInteractive",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            script_path,
        ]

    def error_line(self, stderr: str) -> int | None:
        hits = re.findall(rf"{re.escape(self.file_name)}:(\d+)", stderr)
        if hits:
            return int(hits[0])
        m = re.search(r"\bLine \|\s*\n\s*(\d+) \|", stderr)
        return int(m.group(1)) if m else None
