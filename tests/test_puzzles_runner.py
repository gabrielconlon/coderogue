"""run_puzzle end to end on the shipped content (python always, bash when installed)."""

from __future__ import annotations

from pathlib import Path

import pytest

from coderogue.languages import get
from coderogue.puzzles.runner import RunnerError, find_blank, reference_check, run_puzzle
from coderogue.puzzles.spec import load_all, parse_puzzle

CONTENT = Path(__file__).resolve().parents[1] / "content" / "puzzles"
SPECS = load_all(CONTENT)
LANGS = [
    "python",
    pytest.param("bash", marks=pytest.mark.skipif(get("bash").detect() is None,
                                                  reason="bash not installed")),
]
PUZZLES = ["ch0-01", "ch0-02", "ch0-03", "ch1-05"]


@pytest.mark.parametrize("lang", LANGS)
@pytest.mark.parametrize("pid", PUZZLES)
def test_solution_passes_starter_fails(pid: str, lang: str) -> None:
    spec = SPECS[pid]
    variant = spec.languages[lang]
    good = run_puzzle(spec, lang, variant.solution)
    assert good.passed, good.message
    assert len(good.outcomes) == len(spec.tests)
    bad = run_puzzle(spec, lang, variant.starter)
    assert not bad.passed


@pytest.mark.parametrize("lang", LANGS)
def test_reference_check(lang: str) -> None:
    for pid in PUZZLES:
        (report,) = reference_check(SPECS[pid], lang)
        assert report.ok, report.problems


def test_blank_detection_short_circuits() -> None:
    spec = SPECS["ch1-05"]
    starter = spec.languages["python"].starter
    assert find_blank(starter) == 3
    r = run_puzzle(spec, "python", starter)
    assert r.blank_detected and r.blank_line == 3
    assert r.outcomes == []  # nothing was executed
    assert r.message == "You still have a blank on line 3."


def test_mend_ward_starter_reports_translated_error() -> None:
    spec = SPECS["ch0-03"]
    r = run_puzzle(spec, "python", spec.languages["python"].starter)
    assert not r.blank_detected
    assert r.first_failure is not None and r.first_failure.kind == "stdout"
    assert r.error_line == 4
    assert r.error_translation is not None and "quote" in r.error_translation
    assert "SyntaxError" in r.raw_stderr
    # After fixing the quote, the next error is the prnt typo.
    half = spec.languages["python"].starter.replace('stands!)', 'stands!")')
    r2 = run_puzzle(spec, "python", half)
    assert r2.error_line == 3
    assert r2.error_translation is not None and "`print`" in r2.error_translation


def test_stops_at_first_failing_test() -> None:
    spec = SPECS["ch1-05"]
    code = 'name = input()\nprint("Welcome aboard, Wren. Mind the Null.")\n'
    r = run_puzzle(spec, "python", code)
    assert [o.passed for o in r.outcomes] == [True, False]
    assert r.first_failure is r.outcomes[-1]
    assert r.first_failure.name == "A different rider"
    assert r.first_failure.stdin == "Pell\n"


def test_timeout_reported() -> None:
    spec = SPECS["ch0-01"]
    r = run_puzzle(spec, "python", "while True:\n    pass\n")
    assert r.timed_out
    assert r.first_failure is not None and "Does your loop ever stop?" in r.message


def test_source_checks_block_a_pass() -> None:
    spec = parse_puzzle({
        "id": "src-check", "title": "Src", "chapter": 1, "order": 1,
        "languages": {"python": {
            "starter": "print(___)\n", "hints": ["a", "b", "c"],
            "solution": 'village = "Murmurby"\nprint("Welcome to " + village)\n',
            "source_checks": [{"pattern": r"\bvillage\s*=", "message": "Use village."}],
        }},
        "tests": [{"name": "t", "expect": {"stdout": "Welcome to Murmurby\n"}}],
    })
    r = run_puzzle(spec, "python", 'print("Welcome to Murmurby")\n')
    assert not r.passed and r.first_failure is None
    assert r.source_messages == ["Use village."]
    assert run_puzzle(spec, "python", spec.languages["python"].solution).passed


def test_runner_errors() -> None:
    spec = SPECS["ch0-01"]
    with pytest.raises(RunnerError):
        run_puzzle(spec, "cobol", "x")
    needs_new = parse_puzzle({
        "id": "req", "title": "Req", "chapter": 1, "order": 1, "requires": {"python": ">=99"},
        "languages": {"python": {"starter": "pass\n", "hints": ["a", "b", "c"],
                                 "solution": "print(1)\n"}},
        "tests": [{"name": "t", "expect": {"stdout": "1\n"}}],
    })
    with pytest.raises(RunnerError, match=">=99"):
        run_puzzle(needs_new, "python", "print(1)\n")
