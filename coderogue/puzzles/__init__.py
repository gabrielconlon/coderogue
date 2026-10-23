"""Puzzle system: YAML specs, the subprocess sandbox, output validation and the runner.

Typical game use::

    from coderogue.puzzles import load_all, run_puzzle

    puzzles = load_all(resource_path("content/puzzles"))
    result = run_puzzle(puzzles["ch1-05"], "python", buffer_text)
    if result.passed: ...
"""

from __future__ import annotations

from coderogue.puzzles.runner import (
    PuzzleResult,
    ReferenceReport,
    RunnerError,
    find_blank,
    reference_check,
    run_puzzle,
)
from coderogue.puzzles.sandbox import ExecResult, run_script
from coderogue.puzzles.spec import (
    PuzzleBody,
    PuzzleSpec,
    SpecError,
    load_all,
    load_puzzle,
    parse_puzzle,
)
from coderogue.puzzles.validate import (
    DiffSummary,
    TestOutcome,
    check_test,
    diff_summary,
    normalize,
    source_checks,
)

__all__ = [
    "DiffSummary",
    "ExecResult",
    "PuzzleBody",
    "PuzzleResult",
    "PuzzleSpec",
    "ReferenceReport",
    "RunnerError",
    "SpecError",
    "TestOutcome",
    "check_test",
    "diff_summary",
    "find_blank",
    "load_all",
    "load_puzzle",
    "normalize",
    "parse_puzzle",
    "reference_check",
    "run_puzzle",
    "run_script",
    "source_checks",
]
