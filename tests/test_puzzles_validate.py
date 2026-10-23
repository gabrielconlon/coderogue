"""normalize, diffs, check_test and source checks (no subprocesses)."""

from __future__ import annotations

from coderogue.puzzles.sandbox import ExecResult
from coderogue.puzzles.spec import Expectation, FileExpectation, SourceCheck, TestCase
from coderogue.puzzles.validate import (
    NEWLINE_MARK,
    TRAILING_SPACE_MARK,
    check_test,
    diff_summary,
    first_diff_line,
    normalize,
    source_checks,
)


def _res(stdout: str = "", **kw: object) -> ExecResult:
    base: dict[str, object] = {"stderr": "", "exit_code": 0}
    base.update(kw)
    return ExecResult(stdout=stdout, **base)  # type: ignore[arg-type]


def test_normalize() -> None:
    assert normalize("a  \r\nb\t\r\n\r\n\n") == "a\nb"
    assert normalize("") == ""
    assert normalize("\n\n") == ""
    assert normalize("  lead stays\n") == "  lead stays"
    assert normalize("a\n\nb\n") == "a\n\nb"


def test_first_diff_line() -> None:
    assert first_diff_line("a\nb\n", "a\nb") is None
    assert first_diff_line("a\nb\n", "a\nc\n") == 2
    assert first_diff_line("a\nb\nc\n", "a\nb\n") == 3
    assert first_diff_line("a\n", "a") is None  # normalized: final newline does not matter
    assert first_diff_line("a\n", "a", mode="exact") == 1
    assert first_diff_line("a\n", "a\n", mode="exact") is None


def test_diff_summary_normalized_rows() -> None:
    d = diff_summary("one\ntwo\nthree\n", "one\nTWO\n")
    assert d.first_diff_line == 2
    assert [(r.expected, r.actual, r.differs) for r in d.rows] == [
        ("one", "one", False),
        ("two", "TWO", True),
        ("three", None, True),
    ]
    assert not d.matches


def test_diff_summary_exact_marks_invisible_differences() -> None:
    d = diff_summary("Hello\n", "Hello  ", mode="exact")
    assert d.first_diff_line == 1
    row = d.rows[0]
    assert row.expected == "Hello" + NEWLINE_MARK
    assert row.actual == "Hello" + TRAILING_SPACE_MARK * 2
    assert row.differs


def test_check_test_pass_and_stdout_fail() -> None:
    t = TestCase("greet", "Wren\n", Expectation(stdout="Hi, Wren.\n"))
    ok = check_test(t, _res("Hi, Wren.  \r\n\n"))
    assert ok.passed and ok.kind == "ok"
    bad = check_test(t, _res("Hi, Wren\n"))
    assert not bad.passed
    assert bad.kind == "stdout"
    assert bad.first_diff_line == 1
    assert bad.stdin == "Wren\n"
    assert bad.diff is not None and bad.diff.rows[0].differs


def test_check_test_exact_mode() -> None:
    t = TestCase("exact", "", Expectation(stdout="a\n"), match="exact")
    assert check_test(t, _res("a\n")).passed
    assert not check_test(t, _res("a \n")).passed


def test_check_test_exit_code_timeout_truncation() -> None:
    t = TestCase("t", "", Expectation(stdout="x\n", exit_code=0))
    assert check_test(t, _res("x\n", exit_code=1)).kind == "exit_code"
    to = check_test(t, _res("", timed_out=True, exit_code=None), timeout_s=2)
    assert to.kind == "timeout"
    assert "still chanting after 2 seconds" in to.reason
    assert check_test(t, _res("x" * 10, output_truncated=True)).kind == "output_truncated"


def test_check_test_regex_and_files() -> None:
    t = TestCase("rx", "", Expectation(stdout_regex=r"^\s*4\s*$"))
    assert check_test(t, _res("      4\n")).passed
    assert check_test(t, _res("5\n")).kind == "stdout_regex"
    ft = TestCase("file", "", Expectation(files=(
        FileExpectation("ledger.txt", content="a\nb\n"),
        FileExpectation("log.txt", regex=r"^done$"),
    )))
    good = {"ledger.txt": "a\nb", "log.txt": "start\ndone\n"}
    assert check_test(ft, _res("", files=good)).passed
    assert check_test(ft, _res("", files={})).kind == "file_missing"
    wrong = dict(good, **{"ledger.txt": "a\nc\n"})
    out = check_test(ft, _res("", files=wrong))
    assert out.kind == "file_content" and out.first_diff_line == 2
    assert check_test(ft, _res("", files=dict(good, **{"log.txt": "nope"}))).kind == (
        "file_content")


def test_source_checks() -> None:
    checks = [
        SourceCheck(r"\bvillage\s*=", "Store the name in a variable called village first."),
        SourceCheck(r"print\(", "Use print."),
    ]
    assert source_checks('village = "M"\nprint(village)\n', checks) == []
    assert source_checks('print("Welcome to Murmurby")\n', checks) == [
        "Store the name in a variable called village first."
    ]
