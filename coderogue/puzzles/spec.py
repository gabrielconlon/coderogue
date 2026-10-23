"""Puzzle specs: dataclasses and a validating YAML/JSON loader (schema in DESIGN.md section 5).

``load_puzzle(path)`` returns a :class:`PuzzleSpec` or raises :class:`SpecError` listing every
problem found in the file, so authors fix everything in one pass.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Any

import yaml

from coderogue.languages import LANGUAGE_IDS, parse_version_spec

MATCH_MODES = ("normalized", "exact")
PUZZLE_SUFFIXES = (".yaml", ".yml", ".json")


class SpecError(ValueError):
    """A puzzle file is malformed. ``errors`` holds one message per problem."""

    def __init__(self, source: str, errors: list[str]) -> None:
        self.source = source
        self.errors = errors
        bullet = "\n  - ".join(errors)
        super().__init__(f"{source}: {len(errors)} problem(s):\n  - {bullet}")


@dataclass(frozen=True)
class Fixture:
    """A file written into the sandbox before every test."""

    path: str
    content: str


@dataclass(frozen=True)
class SourceCheck:
    """A regex the player's code must match, with the message shown when it does not."""

    pattern: str
    message: str

    def matches(self, code: str) -> bool:
        """True if ``pattern`` is found anywhere in ``code`` (multiline mode)."""
        return re.search(self.pattern, code, re.MULTILINE) is not None


@dataclass(frozen=True)
class LanguageVariant:
    """One language's starter, hints, solution and source checks."""

    starter: str
    hints: tuple[str, str, str]
    solution: str
    source_checks: tuple[SourceCheck, ...] = ()


@dataclass(frozen=True)
class FileExpectation:
    """A file that must exist in the sandbox after the run (``content`` xor ``regex``)."""

    path: str
    content: str | None = None
    regex: str | None = None


@dataclass(frozen=True)
class Expectation:
    """What a test expects. ``stdout`` and ``stdout_regex`` are mutually exclusive."""

    stdout: str | None = None
    stdout_regex: str | None = None
    exit_code: int = 0
    files: tuple[FileExpectation, ...] = ()


@dataclass(frozen=True)
class TestCase:
    """One test: stdin in, expectations out."""

    __test__ = False  # keep pytest from collecting this class

    name: str
    stdin: str = ""
    expect: Expectation = field(default_factory=Expectation)
    match: str = "normalized"


@dataclass(frozen=True)
class Limits:
    """Per-test limits."""

    timeout_s: float = 2.0
    max_stdout_kb: int = 16

    @property
    def max_output_bytes(self) -> int:
        """``max_stdout_kb`` in bytes."""
        return self.max_stdout_kb * 1024


@dataclass(frozen=True)
class Reward:
    """What solving the altar grants."""

    xp: int = 0
    items: tuple[str, ...] = ()
    unlocks: tuple[str, ...] = ()
    world_effect: str = ""


@dataclass(frozen=True)
class PuzzleBody:
    """The solvable part of a puzzle: shared by plain puzzles and each boss phase."""

    lore: str
    languages: dict[str, LanguageVariant]
    tests: tuple[TestCase, ...]
    fixtures: tuple[Fixture, ...] = ()
    limits: Limits = field(default_factory=Limits)
    title: str = ""


@dataclass(frozen=True)
class PuzzleSpec:
    """A whole altar. For bosses, ``phases`` holds the bodies solved in order."""

    id: str
    title: str
    chapter: int
    order: int
    body: PuzzleBody
    optional: bool = False
    concepts: tuple[str, ...] = ()
    vim_skill: str = ""
    requires: dict[str, str] = field(default_factory=dict)
    phases: tuple[PuzzleBody, ...] = ()
    reward: Reward = field(default_factory=Reward)
    source_path: str = ""

    # Convenience pass-throughs to the main body.
    @property
    def lore(self) -> str:
        """Lore text of the main body."""
        return self.body.lore

    @property
    def languages(self) -> dict[str, LanguageVariant]:
        """Language variants of the main body."""
        return self.body.languages

    @property
    def tests(self) -> tuple[TestCase, ...]:
        """Tests of the main body."""
        return self.body.tests

    @property
    def fixtures(self) -> tuple[Fixture, ...]:
        """Fixtures of the main body."""
        return self.body.fixtures

    @property
    def limits(self) -> Limits:
        """Limits of the main body."""
        return self.body.limits

    @property
    def is_boss(self) -> bool:
        """True if the puzzle is solved in phases."""
        return bool(self.phases)

    def bodies(self) -> list[tuple[int | None, PuzzleBody]]:
        """``[(None, body)]`` for a plain puzzle, ``[(0, p0), (1, p1), ...]`` for a boss."""
        if self.phases:
            return [(i, body) for i, body in enumerate(self.phases)]
        return [(None, self.body)]

    def body_for(self, phase: int | None) -> PuzzleBody:
        """The body to run: the main one, or ``phases[phase]``."""
        if phase is None:
            if self.phases and not self.body.tests:
                raise IndexError(f"{self.id} is a boss; pass a phase index")
            return self.body
        if not 0 <= phase < len(self.phases):
            raise IndexError(f"{self.id} has no phase {phase}")
        return self.phases[phase]

    def language_ids(self) -> list[str]:
        """Languages offered by every body of this puzzle."""
        ids: set[str] | None = None
        for _, body in self.bodies():
            keys = set(body.languages)
            ids = keys if ids is None else ids & keys
        return [lid for lid in LANGUAGE_IDS if ids and lid in ids]


# ------------------------------------------------------------------------------------------
# Loading and validation
# ------------------------------------------------------------------------------------------

_TOP_KEYS = {
    "id", "title", "chapter", "order", "optional", "concepts", "vim_skill", "lore",
    "requires", "limits", "fixtures", "languages", "tests", "phases", "reward",
}
_BODY_KEYS = {"title", "lore", "limits", "fixtures", "languages", "tests"}
_VARIANT_KEYS = {"starter", "hints", "solution", "source_checks"}
_TEST_KEYS = {"name", "stdin", "expect", "match"}
_EXPECT_KEYS = {"stdout", "stdout_regex", "exit_code", "files"}
_REWARD_KEYS = {"xp", "items", "unlocks", "world_effect"}


class _Collector:
    """Accumulates validation errors with a dotted location prefix."""

    def __init__(self) -> None:
        self.errors: list[str] = []

    def add(self, where: str, msg: str) -> None:
        self.errors.append(f"{where}: {msg}" if where else msg)

    def unknown_keys(self, where: str, data: dict[str, Any], allowed: set[str]) -> None:
        for key in sorted(set(data) - allowed):
            self.add(where, f"unknown key {key!r} (allowed: {', '.join(sorted(allowed))})")

    def text(self, where: str, value: Any, *, required: bool = True) -> str:
        if value is None:
            if required:
                self.add(where, "is required")
            return ""
        if not isinstance(value, str):
            self.add(where, f"must be text, got {type(value).__name__}")
            return ""
        return value

    def regex(self, where: str, pattern: Any) -> str:
        text = self.text(where, pattern)
        if text:
            try:
                re.compile(text)
            except re.error as exc:
                self.add(where, f"invalid regex: {exc}")
        return text

    def str_list(self, where: str, value: Any) -> tuple[str, ...]:
        if value is None:
            return ()
        if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
            self.add(where, "must be a list of text items")
            return ()
        return tuple(value)

    def mapping(self, where: str, value: Any) -> dict[str, Any] | None:
        if value is None:
            return None
        if not isinstance(value, dict):
            self.add(where, f"must be a mapping, got {type(value).__name__}")
            return None
        return value


def _safe_rel_path(c: _Collector, where: str, value: Any) -> str:
    path = c.text(where, value)
    if path:
        p = PurePosixPath(path.replace("\\", "/"))
        if p.is_absolute() or ".." in p.parts or re.match(r"^[A-Za-z]:", path):
            c.add(where, f"must be a relative path inside the sandbox, got {path!r}")
    return path


def _int(c: _Collector, where: str, value: Any, default: int | None = None) -> int:
    if value is None:
        if default is None:
            c.add(where, "is required")
            return 0
        return default
    if isinstance(value, bool) or not isinstance(value, int):
        c.add(where, f"must be a whole number, got {value!r}")
        return default or 0
    return value


def _parse_limits(c: _Collector, where: str, raw: Any, base: Limits) -> Limits:
    data = c.mapping(where, raw)
    if data is None:
        return base
    c.unknown_keys(where, data, {"timeout_s", "max_stdout_kb"})
    timeout = data.get("timeout_s", base.timeout_s)
    if isinstance(timeout, bool) or not isinstance(timeout, (int, float)) or not (
        0 < timeout <= 60
    ):
        c.add(f"{where}.timeout_s", f"must be a number of seconds in (0, 60], got {timeout!r}")
        timeout = base.timeout_s
    kb = _int(c, f"{where}.max_stdout_kb", data.get("max_stdout_kb"), base.max_stdout_kb)
    if kb <= 0:
        c.add(f"{where}.max_stdout_kb", "must be positive")
        kb = base.max_stdout_kb
    return Limits(timeout_s=float(timeout), max_stdout_kb=kb)


def _parse_fixtures(c: _Collector, where: str, raw: Any) -> tuple[Fixture, ...]:
    if raw is None:
        return ()
    if not isinstance(raw, list):
        c.add(where, "must be a list of {path, content}")
        return ()
    out = []
    for i, item in enumerate(raw):
        w = f"{where}[{i}]"
        data = c.mapping(w, item)
        if data is None:
            continue
        c.unknown_keys(w, data, {"path", "content"})
        path = _safe_rel_path(c, f"{w}.path", data.get("path"))
        content = c.text(f"{w}.content", data.get("content"))
        out.append(Fixture(path, content))
    return tuple(out)


def _parse_variant(c: _Collector, where: str, raw: Any) -> LanguageVariant | None:
    data = c.mapping(where, raw)
    if data is None:
        c.add(where, "must be a mapping with starter, hints, solution")
        return None
    c.unknown_keys(where, data, _VARIANT_KEYS)
    starter = c.text(f"{where}.starter", data.get("starter"))
    solution = c.text(f"{where}.solution", data.get("solution"))
    if "solution" in data and not solution.strip():
        c.add(f"{where}.solution", "must not be empty")
    if "___" in solution:
        c.add(f"{where}.solution", "still contains a ___ blank")
    hints_raw = data.get("hints")
    hints: tuple[str, str, str] = ("", "", "")
    if not isinstance(hints_raw, list) or not all(isinstance(h, str) for h in hints_raw):
        c.add(f"{where}.hints", "must be a list of exactly 3 text hints")
    elif len(hints_raw) != 3:
        c.add(f"{where}.hints", f"must have exactly 3 hints (nudge, pointer, near-solution), "
              f"got {len(hints_raw)}")
    else:
        hints = (hints_raw[0], hints_raw[1], hints_raw[2])
    checks: list[SourceCheck] = []
    raw_checks = data.get("source_checks") or []
    if not isinstance(raw_checks, list):
        c.add(f"{where}.source_checks", "must be a list of {pattern, message}")
        raw_checks = []
    for i, item in enumerate(raw_checks):
        w = f"{where}.source_checks[{i}]"
        d = c.mapping(w, item)
        if d is None:
            continue
        c.unknown_keys(w, d, {"pattern", "message"})
        checks.append(
            SourceCheck(c.regex(f"{w}.pattern", d.get("pattern")),
                        c.text(f"{w}.message", d.get("message")))
        )
    return LanguageVariant(starter, hints, solution, tuple(checks))


def _parse_expect(c: _Collector, where: str, raw: Any) -> Expectation:
    data = c.mapping(where, raw)
    if data is None:
        c.add(where, "is required")
        return Expectation()
    c.unknown_keys(where, data, _EXPECT_KEYS)
    stdout = c.text(f"{where}.stdout", data.get("stdout"), required=False) or None
    if data.get("stdout") == "":
        stdout = ""
    regex = c.regex(f"{where}.stdout_regex", data["stdout_regex"]) if (
        "stdout_regex" in data) else None
    if stdout is not None and regex is not None:
        c.add(where, "use either stdout or stdout_regex, not both")
    files: list[FileExpectation] = []
    raw_files = data.get("files") or []
    if not isinstance(raw_files, list):
        c.add(f"{where}.files", "must be a list")
        raw_files = []
    for i, item in enumerate(raw_files):
        w = f"{where}.files[{i}]"
        d = c.mapping(w, item)
        if d is None:
            continue
        c.unknown_keys(w, d, {"path", "content", "regex"})
        path = _safe_rel_path(c, f"{w}.path", d.get("path"))
        content = c.text(f"{w}.content", d.get("content"), required=False) if (
            "content" in d) else None
        fregex = c.regex(f"{w}.regex", d.get("regex")) if "regex" in d else None
        if (content is None) == (fregex is None):
            c.add(w, "needs exactly one of content or regex")
        files.append(FileExpectation(path, content, fregex))
    if stdout is None and regex is None and not files:
        c.add(where, "expects nothing: give stdout, stdout_regex, or files")
    exit_code = _int(c, f"{where}.exit_code", data.get("exit_code"), 0)
    return Expectation(stdout, regex, exit_code, tuple(files))


def _parse_tests(c: _Collector, where: str, raw: Any) -> tuple[TestCase, ...]:
    if not isinstance(raw, list) or not raw:
        c.add(where, "must be a non-empty list of tests")
        return ()
    out = []
    for i, item in enumerate(raw):
        w = f"{where}[{i}]"
        data = c.mapping(w, item)
        if data is None:
            continue
        c.unknown_keys(w, data, _TEST_KEYS)
        name = c.text(f"{w}.name", data.get("name"))
        stdin = c.text(f"{w}.stdin", data.get("stdin"), required=False)
        match = data.get("match", "normalized")
        if match not in MATCH_MODES:
            c.add(f"{w}.match", f"must be one of {MATCH_MODES}, got {match!r}")
            match = "normalized"
        out.append(TestCase(name, stdin, _parse_expect(c, f"{w}.expect", data.get("expect")),
                            match))
    return tuple(out)


def _parse_languages(c: _Collector, where: str, raw: Any) -> dict[str, LanguageVariant]:
    data = c.mapping(where, raw)
    if not data:
        c.add(where, "must define at least one language variant")
        return {}
    out: dict[str, LanguageVariant] = {}
    for lid, body in data.items():
        if lid not in LANGUAGE_IDS:
            c.add(where, f"unknown language id {lid!r} (known: {', '.join(LANGUAGE_IDS)})")
            continue
        variant = _parse_variant(c, f"{where}.{lid}", body)
        if variant is not None:
            out[lid] = variant
    return out


def _parse_body(c: _Collector, where: str, data: dict[str, Any], base_limits: Limits,
                base_fixtures: tuple[Fixture, ...]) -> PuzzleBody:
    prefix = f"{where}." if where else ""
    limits = _parse_limits(c, f"{prefix}limits", data.get("limits"), base_limits)
    fixtures = (_parse_fixtures(c, f"{prefix}fixtures", data["fixtures"])
                if "fixtures" in data else base_fixtures)
    return PuzzleBody(
        lore=c.text(f"{prefix}lore", data.get("lore"), required=False),
        languages=_parse_languages(c, f"{prefix}languages", data.get("languages")),
        tests=_parse_tests(c, f"{prefix}tests", data.get("tests")),
        fixtures=fixtures,
        limits=limits,
        title=c.text(f"{prefix}title", data.get("title"), required=False),
    )


def parse_puzzle(data: Any, source: str = "<puzzle>") -> PuzzleSpec:
    """Validate a decoded YAML/JSON mapping and build a :class:`PuzzleSpec`."""
    c = _Collector()
    if not isinstance(data, dict):
        raise SpecError(source, [f"top level must be a mapping, got {type(data).__name__}"])
    c.unknown_keys("", data, _TOP_KEYS)
    pid = c.text("id", data.get("id"))
    if pid and not re.fullmatch(r"[a-z0-9][a-z0-9_-]*", pid):
        c.add("id", f"must be lowercase letters, digits, - or _, got {pid!r}")
    title = c.text("title", data.get("title"))
    chapter = _int(c, "chapter", data.get("chapter"))
    order = _int(c, "order", data.get("order"))
    optional = data.get("optional", False)
    if not isinstance(optional, bool):
        c.add("optional", "must be true or false")
        optional = False

    requires: dict[str, str] = {}
    req = c.mapping("requires", data.get("requires")) or {}
    for lid, spec in req.items():
        if lid not in LANGUAGE_IDS:
            c.add("requires", f"unknown language id {lid!r}")
            continue
        try:
            parse_version_spec(str(spec))
            requires[lid] = str(spec)
        except ValueError as exc:
            c.add(f"requires.{lid}", str(exc))

    phases_raw = data.get("phases") or []
    if not isinstance(phases_raw, list):
        c.add("phases", "must be a list")
        phases_raw = []
    top_limits = _parse_limits(c, "limits", data.get("limits"), Limits())
    top_fixtures = _parse_fixtures(c, "fixtures", data.get("fixtures"))

    if phases_raw:
        # Boss: the top level carries shared lore/limits/fixtures; each phase is a body.
        top_body = PuzzleBody(
            lore=c.text("lore", data.get("lore"), required=False),
            languages={}, tests=(), fixtures=top_fixtures, limits=top_limits,
        )
        if "languages" in data or "tests" in data:
            c.add("", "a boss puzzle puts languages and tests inside each phase, not at the top")
        phases = []
        for i, raw in enumerate(phases_raw):
            w = f"phases[{i}]"
            pdata = c.mapping(w, raw)
            if pdata is None:
                continue
            c.unknown_keys(w, pdata, _BODY_KEYS)
            phases.append(_parse_body(c, w, pdata, top_limits, top_fixtures))
        body = top_body
    else:
        # limits/fixtures were already parsed above; do not report their errors twice.
        rest = {k: v for k, v in data.items() if k not in ("limits", "fixtures")}
        body = _parse_body(c, "", rest, top_limits, top_fixtures)
        phases = []

    reward_data = c.mapping("reward", data.get("reward")) or {}
    c.unknown_keys("reward", reward_data, _REWARD_KEYS)
    reward = Reward(
        xp=_int(c, "reward.xp", reward_data.get("xp"), 0),
        items=c.str_list("reward.items", reward_data.get("items")),
        unlocks=c.str_list("reward.unlocks", reward_data.get("unlocks")),
        world_effect=c.text("reward.world_effect", reward_data.get("world_effect"),
                            required=False),
    )

    if c.errors:
        raise SpecError(source, c.errors)
    return PuzzleSpec(
        id=pid, title=title, chapter=chapter, order=order, body=body, optional=optional,
        concepts=c.str_list("concepts", data.get("concepts")),
        vim_skill=c.text("vim_skill", data.get("vim_skill"), required=False),
        requires=requires, phases=tuple(phases), reward=reward, source_path=source,
    )


def load_puzzle(path: str | Path) -> PuzzleSpec:
    """Read and validate one puzzle file (YAML or JSON)."""
    p = Path(path)
    try:
        data = yaml.safe_load(p.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise SpecError(str(p), [f"not valid YAML: {exc}"]) from exc
    except OSError as exc:
        raise SpecError(str(p), [f"cannot read file: {exc}"]) from exc
    return parse_puzzle(data, str(p))


def puzzle_files(content_dir: str | Path) -> list[Path]:
    """Every puzzle file under ``content_dir``, sorted for stable ordering."""
    root = Path(content_dir)
    return sorted(p for p in root.rglob("*") if p.is_file() and p.suffix in PUZZLE_SUFFIXES)


def load_all(content_dir: str | Path) -> dict[str, PuzzleSpec]:
    """Load every puzzle under ``content_dir`` keyed by id.

    Raises :class:`SpecError` on the first malformed file, or on duplicate ids.
    """
    out: dict[str, PuzzleSpec] = {}
    for path in puzzle_files(content_dir):
        spec = load_puzzle(path)
        if spec.id in out:
            raise SpecError(str(path), [f"duplicate id {spec.id!r} (also in "
                                        f"{out[spec.id].source_path})"])
        out[spec.id] = spec
    return out
