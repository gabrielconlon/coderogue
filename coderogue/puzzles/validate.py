"""Compare a run against a test's expectations, and render diffs for the failure panel.

* :func:`normalize` - the "normalized" match from DESIGN.md section 5.
* :func:`check_test` - one :class:`TestOutcome` per test.
* :func:`source_checks` - plain-language messages for unmet source regexes.
* :func:`diff_summary` - rows ready for an Expected / "Your spell said" side-by-side view, with
  trailing spaces shown as ``·`` and a missing final newline as ``⏎``.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass, field

from coderogue.puzzles.sandbox import ExecResult
from coderogue.puzzles.spec import SourceCheck, TestCase

TRAILING_SPACE_MARK = "·"
NEWLINE_MARK = "⏎"


def normalize(s: str) -> str:
    """CRLF -> LF, strip trailing whitespace on each line, drop trailing blank lines."""
    lines = [line.rstrip() for line in s.replace("\r\n", "\n").replace("\r", "\n").split("\n")]
    while lines and not lines[-1]:
        lines.pop()
    return "\n".join(lines)


def _crlf_to_lf(s: str) -> str:
    """Line endings only: Windows ``\\r\\n`` becomes ``\\n``; spaces and tabs are kept."""
    return s.replace("\r\n", "\n")


def _lines_for(s: str, mode: str) -> list[str]:
    if mode == "exact":
        text = s.replace("\r\n", "\n")
        return text.split("\n")[:-1] if text.endswith("\n") else text.split("\n") if text else []
    norm = normalize(s)
    return norm.split("\n") if norm else []


def first_diff_line(expected: str, actual: str, mode: str = "normalized") -> int | None:
    """1-based number of the first differing line, or ``None`` if the texts match."""
    if mode == "exact":
        if _crlf_to_lf(expected) == _crlf_to_lf(actual):
            return None
    elif normalize(expected) == normalize(actual):
        return None
    exp, act = _lines_for(expected, mode), _lines_for(actual, mode)
    for i, (a, b) in enumerate(zip(exp, act, strict=False)):
        if a != b:
            return i + 1
    if len(exp) != len(act):
        return min(len(exp), len(act)) + 1
    # Same lines, so the only difference is the final newline (exact mode).
    return max(len(exp), 1)


def visible(line: str) -> str:
    """Show trailing spaces as ``·`` and tabs as ``→`` so invisible differences show up."""
    stripped = line.rstrip(" \t")
    tail = line[len(stripped):].replace(" ", TRAILING_SPACE_MARK).replace("\t", "→")
    return stripped + tail


@dataclass(frozen=True)
class DiffRow:
    """One line pair. ``None`` means that side has no such line."""

    line_no: int
    expected: str | None
    actual: str | None
    differs: bool


@dataclass(frozen=True)
class DiffSummary:
    """Side-by-side rows plus the first differing line (1-based) for highlighting."""

    rows: tuple[DiffRow, ...]
    first_diff_line: int | None
    mode: str = "normalized"

    @property
    def matches(self) -> bool:
        """True if there is no difference."""
        return self.first_diff_line is None


def diff_summary(expected: str, actual: str, mode: str = "normalized") -> DiffSummary:
    """Line-aligned rows for the failure panel.

    In ``normalized`` mode lines are compared after :func:`normalize`, so whitespace that does
    not matter is not shown. In ``exact`` mode trailing spaces are marked ``·`` and, if only one
    side ends with a newline, that side's last line gets a ``⏎`` marker.
    """
    exp, act = _lines_for(expected, mode), _lines_for(actual, mode)
    rows: list[DiffRow] = []
    for i in range(max(len(exp), len(act))):
        e = exp[i] if i < len(exp) else None
        a = act[i] if i < len(act) else None
        rows.append(DiffRow(
            i + 1,
            visible(e) if e is not None else None,
            visible(a) if a is not None else None,
            e != a,
        ))
    fd = first_diff_line(expected, actual, mode)
    if mode == "exact":
        e_nl = expected.replace("\r\n", "\n").endswith("\n")
        a_nl = actual.replace("\r\n", "\n").endswith("\n")
        if e_nl != a_nl and rows:
            last = rows[-1]
            exp_txt, act_txt = last.expected, last.actual
            if e_nl and exp_txt is not None:
                exp_txt += NEWLINE_MARK
            if a_nl and act_txt is not None:
                act_txt += NEWLINE_MARK
            rows[-1] = DiffRow(last.line_no, exp_txt, act_txt, True)
    return DiffSummary(tuple(rows), fd, mode)


@dataclass
class TestOutcome:
    """Result of one test. ``reason`` is a plain sentence for the failure panel."""

    __test__ = False  # keep pytest from collecting this class

    passed: bool
    name: str
    expected: str = ""
    actual: str = ""
    first_diff_line: int | None = None
    reason: str = ""
    #: Short machine code: ok, stdout, stdout_regex, exit_code, file_missing, file_content,
    #: timeout, output_truncated, blank.
    kind: str = "ok"
    stdin: str = ""
    match: str = "normalized"
    diff: DiffSummary | None = field(default=None, repr=False)


def _text_matches(expected: str, actual: str, mode: str) -> bool:
    if mode == "exact":
        # Exact still forgives Windows line endings, but not trailing spaces or newlines.
        return _crlf_to_lf(expected) == _crlf_to_lf(actual)
    return normalize(expected) == normalize(actual)


def check_test(test: TestCase, result: ExecResult, timeout_s: float | None = None) -> TestOutcome:
    """Judge ``result`` against ``test``. Checks, in order: timeout, output cap, stdout, exit
    code, then files."""
    base = {"name": test.name, "stdin": test.stdin, "match": test.match, "actual": result.stdout}
    exp = test.expect
    if result.timed_out:
        secs = f"{timeout_s:g} seconds" if timeout_s else "its time limit"
        return TestOutcome(False, reason=f"Your spell was still chanting after {secs}. "
                           "Does your loop ever stop?", kind="timeout", **base)
    if result.output_truncated:
        return TestOutcome(False, reason="Your spell said far too much; the Terminal stopped "
                           "listening. Is something printing in a loop that never ends?",
                           kind="output_truncated", **base)
    if exp.stdout is not None and not _text_matches(exp.stdout, result.stdout, test.match):
        d = diff_summary(exp.stdout, result.stdout, test.match)
        line = d.first_diff_line
        return TestOutcome(False, expected=exp.stdout, first_diff_line=line, kind="stdout",
                           reason=f"The output differs from line {line}.", diff=d, **base)
    if exp.stdout_regex is not None:
        text = result.stdout.replace("\r\n", "\n")
        if not re.search(exp.stdout_regex, text, re.MULTILINE):
            return TestOutcome(False, expected=exp.stdout_regex, kind="stdout_regex",
                               reason="The output does not have the expected shape.", **base)
    if result.exit_code != exp.exit_code:
        return TestOutcome(False, expected=exp.stdout or "", kind="exit_code",
                           reason=f"The spell ended with code {result.exit_code}, but the "
                           f"Terminal wanted {exp.exit_code}. Did an error stop it early?",
                           **base)
    for fe in exp.files:
        if fe.path not in result.files:
            return TestOutcome(False, expected=fe.content or fe.regex or "", kind="file_missing",
                               reason=f"The Terminal expected a file named {fe.path}, "
                               "but none was written.", **base)
        got = result.files[fe.path]
        if fe.content is not None and not _text_matches(fe.content, got, test.match):
            d = diff_summary(fe.content, got, test.match)
            return TestOutcome(False, name=test.name, stdin=test.stdin, match=test.match,
                               expected=fe.content, actual=got, kind="file_content",
                               first_diff_line=d.first_diff_line, diff=d,
                               reason=f"{fe.path} differs from line {d.first_diff_line}.")
        if fe.regex is not None and not re.search(fe.regex, got, re.MULTILINE):
            return TestOutcome(False, name=test.name, stdin=test.stdin, match=test.match,
                               expected=fe.regex, actual=got, kind="file_content",
                               reason=f"{fe.path} does not have the expected shape.")
    return TestOutcome(True, expected=exp.stdout or exp.stdout_regex or "", kind="ok", **base)


_FULL_LINE_COMMENT = re.compile(r"^[ \t]*#.*$", re.MULTILINE)


def strip_comment_lines(code: str) -> str:
    """``code`` with every full-line ``#`` comment blanked (python, bash and PowerShell all use
    ``#``). Line numbers are kept. Trailing ``x = 1  # note`` comments and PowerShell ``<# #>``
    blocks are left alone: telling them apart from ``#`` inside strings needs a real parser."""
    return _FULL_LINE_COMMENT.sub("", code.replace("\r\n", "\n"))


def source_checks(code: str, checks: Iterable[SourceCheck]) -> list[str]:
    """Messages for every source check whose pattern is missing from ``code``.

    Patterns are matched against the code with full-line comments removed (see
    :func:`strip_comment_lines`), so a check cannot be satisfied, or tripped, by a comment.
    """
    stripped = strip_comment_lines(code)
    return [c.message for c in checks if not c.matches(stripped)]
