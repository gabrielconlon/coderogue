"""Run a player's spell against a puzzle and decide whether the altar lights.

Game-facing entry point: :func:`run_puzzle`. The content linter uses :func:`reference_check`.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from coderogue.languages import Language, LanguageRuntime, get
from coderogue.puzzles.sandbox import run_script
from coderogue.puzzles.spec import PuzzleBody, PuzzleSpec
from coderogue.puzzles.validate import TestOutcome, check_test, source_checks

BLANK = "___"


class RunnerError(RuntimeError):
    """The puzzle cannot be run here (language missing, too old, or not offered)."""


@dataclass
class PuzzleResult:
    """Outcome of one cast. ``passed`` means every test passed and every source check held."""

    passed: bool
    blank_detected: bool = False
    #: 1-based line of the first ``___`` blank, when ``blank_detected``.
    blank_line: int | None = None
    source_messages: list[str] = field(default_factory=list)
    outcomes: list[TestOutcome] = field(default_factory=list)
    first_failure: TestOutcome | None = None
    #: Moth's plain-language reading of the failing run's stderr.
    error_translation: str | None = None
    #: Line the error points at (for the editor gutter), if known.
    error_line: int | None = None
    raw_stderr: str = ""
    timed_out: bool = False

    @property
    def message(self) -> str:
        """One sentence summarising the result for Moth's speech bubble."""
        if self.passed:
            return "The altar lights!"
        if self.blank_detected:
            return f"You still have a blank on line {self.blank_line}."
        if self.error_translation:
            return self.error_translation
        if self.first_failure is not None:
            return self.first_failure.reason
        if self.source_messages:
            return self.source_messages[0]
        return "The spell did not work yet."


def find_blank(code: str) -> int | None:
    """1-based line number of the first ``___`` blank in ``code``, or ``None``."""
    for i, line in enumerate(code.splitlines(), start=1):
        if BLANK in line:
            return i
    return None


def resolve_runtime(spec: PuzzleSpec, language: Language) -> LanguageRuntime:
    """The runtime to use for ``language``, checked against ``spec.requires``."""
    runtime = language.detect()
    if runtime is None:
        raise RunnerError(f"{language.display_name} was not found on this computer.")
    want = spec.requires.get(language.id)
    if want and not language.version_satisfies(runtime, want):
        raise RunnerError(
            f"{spec.title} needs {language.display_name} {want}, but this computer has "
            f"{runtime.version_str} ({runtime.executable})."
        )
    return runtime


def _run_body(
    body: PuzzleBody,
    language: Language,
    runtime: LanguageRuntime,
    code: str,
) -> PuzzleResult:
    variant = body.languages[language.id]
    outcomes: list[TestOutcome] = []
    failure: TestOutcome | None = None
    stderr = ""
    translation: str | None = None
    err_line: int | None = None
    timed_out = False
    for test in body.tests:
        stdin = test.stdin
        if stdin and not stdin.endswith("\n"):
            stdin += "\n"
        result = run_script(
            language, runtime, code, stdin, body.fixtures,
            timeout_s=body.limits.timeout_s,
            max_output_bytes=body.limits.max_output_bytes,
        )
        outcome = check_test(test, result, body.limits.timeout_s)
        outcomes.append(outcome)
        if not outcome.passed:
            failure = outcome
            stderr = result.stderr
            timed_out = result.timed_out
            translation = language.translate_error(stderr)
            err_line = language.error_line(stderr)
            break
    messages = source_checks(code, variant.source_checks)
    return PuzzleResult(
        passed=failure is None and not messages,
        source_messages=messages,
        outcomes=outcomes,
        first_failure=failure,
        error_translation=translation,
        error_line=err_line,
        raw_stderr=stderr,
        timed_out=timed_out,
    )


def run_puzzle(
    spec: PuzzleSpec,
    language_id: str,
    code: str,
    phase: int | None = None,
) -> PuzzleResult:
    """Cast ``code`` (written in ``language_id``) at ``spec`` (or one boss ``phase``).

    Short-circuits without running anything if the code still has a ``___`` blank. Tests run
    in order and stop at the first failure, which is reported in full. Source checks are
    evaluated on every cast; a cast passes only if all tests pass and all checks hold.

    Raises :class:`RunnerError` if the language is unknown, not offered by the puzzle, missing
    from this machine, or older than ``spec.requires`` allows.
    """
    body = spec.body_for(phase)
    try:
        language = get(language_id)
    except KeyError as exc:
        raise RunnerError(f"unknown language {language_id!r}") from exc
    if language_id not in body.languages:
        raise RunnerError(f"{spec.title} has no {language.display_name} version.")
    blank = find_blank(code)
    if blank is not None:
        return PuzzleResult(passed=False, blank_detected=True, blank_line=blank,
                            error_line=blank)
    runtime = resolve_runtime(spec, language)
    return _run_body(body, language, runtime, code)


@dataclass
class ReferenceReport:
    """Content-lint result for one puzzle (or phase) in one language."""

    puzzle_id: str
    language_id: str
    phase: int | None
    solution_passed: bool
    starter_failed: bool
    problems: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        """True when the solution passes and the starter does not."""
        return self.solution_passed and self.starter_failed and not self.problems


def _describe(result: PuzzleResult) -> str:
    if result.first_failure is not None:
        f = result.first_failure
        detail = f"test {f.name!r}: {f.reason}"
        if result.raw_stderr.strip():
            detail += f" stderr: {result.raw_stderr.strip().splitlines()[-1]}"
        return detail
    if result.source_messages:
        return "source check: " + "; ".join(result.source_messages)
    return "failed"


def reference_check(spec: PuzzleSpec, language_id: str) -> list[ReferenceReport]:
    """Lint ``spec`` in one language: each solution must pass, each starter must not.

    Returns one report per body (one for a plain puzzle, one per phase for a boss).
    Raises :class:`RunnerError` if the language cannot run here.
    """
    reports: list[ReferenceReport] = []
    for phase, body in spec.bodies():
        variant = body.languages.get(language_id)
        if variant is None:
            reports.append(ReferenceReport(spec.id, language_id, phase, False, False,
                                           [f"no {language_id} variant"]))
            continue
        sol = run_puzzle(spec, language_id, variant.solution, phase)
        starter = run_puzzle(spec, language_id, variant.starter, phase)
        problems: list[str] = []
        if not sol.passed:
            problems.append("solution fails: " + _describe(sol))
        if starter.passed:
            problems.append("starter already passes every test (it should need work)")
        reports.append(ReferenceReport(spec.id, language_id, phase, sol.passed,
                                       not starter.passed, problems))
    return reports
