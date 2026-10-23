"""Puzzle spec loading and validation errors."""

from __future__ import annotations

import copy
from pathlib import Path
from typing import Any

import pytest
import yaml

from coderogue.puzzles.spec import SpecError, load_all, load_puzzle, parse_puzzle

CONTENT = Path(__file__).resolve().parents[1] / "content" / "puzzles"


def _minimal() -> dict[str, Any]:
    return {
        "id": "t-01",
        "title": "Test",
        "chapter": 0,
        "order": 1,
        "languages": {
            "python": {
                "starter": "print(___)\n",
                "hints": ["a", "b", "c"],
                "solution": "print('hi')\n",
            }
        },
        "tests": [{"name": "says hi", "expect": {"stdout": "hi\n"}}],
    }


def _errors(data: dict[str, Any]) -> list[str]:
    with pytest.raises(SpecError) as info:
        parse_puzzle(data, "test.yaml")
    return info.value.errors


def test_minimal_parses_with_defaults() -> None:
    spec = parse_puzzle(_minimal())
    assert spec.id == "t-01"
    assert spec.limits.timeout_s == 2.0
    assert spec.limits.max_output_bytes == 16 * 1024
    assert spec.tests[0].match == "normalized"
    assert spec.tests[0].expect.exit_code == 0
    assert spec.language_ids() == ["python"]
    assert not spec.is_boss


def test_hints_must_be_exactly_three() -> None:
    data = _minimal()
    data["languages"]["python"]["hints"] = ["only", "two"]
    errs = _errors(data)
    assert any("exactly 3 hints" in e for e in errs)


def test_unknown_language_id() -> None:
    data = _minimal()
    data["languages"]["rust"] = copy.deepcopy(data["languages"]["python"])
    errs = _errors(data)
    assert any("unknown language id 'rust'" in e for e in errs)


def test_missing_solution_and_blank_in_solution() -> None:
    data = _minimal()
    del data["languages"]["python"]["solution"]
    assert any("languages.python.solution: is required" in e for e in _errors(data))
    data = _minimal()
    data["languages"]["python"]["solution"] = "print(___)\n"
    assert any("___" in e for e in _errors(data))


def test_collects_several_errors_at_once() -> None:
    data = _minimal()
    data["tests"][0]["match"] = "fuzzy"
    data["tests"][0]["expect"]["stdout_regex"] = "("
    data["limits"] = {"timeout_s": -1}
    data["requires"] = {"bash": "four-ish"}
    data["typo_key"] = 1
    errs = _errors(data)
    joined = "\n".join(errs)
    assert "match" in joined and "fuzzy" in joined
    assert "invalid regex" in joined
    assert "either stdout or stdout_regex" in joined
    assert "timeout_s" in joined
    assert "requires.bash" in joined
    assert "unknown key 'typo_key'" in joined
    assert len(errs) >= 6


def test_fixture_and_file_paths_must_stay_inside() -> None:
    data = _minimal()
    data["fixtures"] = [{"path": "../escape.txt", "content": "x"}]
    data["tests"][0]["expect"]["files"] = [{"path": "/etc/passwd", "content": "x"}]
    errs = _errors(data)
    assert sum("relative path" in e for e in errs) == 2


def test_file_expectation_needs_content_or_regex() -> None:
    data = _minimal()
    data["tests"][0]["expect"]["files"] = [{"path": "out.txt"}]
    assert any("exactly one of content or regex" in e for e in _errors(data))


def test_empty_tests_rejected() -> None:
    data = _minimal()
    data["tests"] = []
    assert any("non-empty list" in e for e in _errors(data))


def test_boss_phases() -> None:
    base = _minimal()
    data = {k: base[k] for k in ("id", "title", "chapter", "order")}
    data["fixtures"] = [{"path": "a.txt", "content": "A\n"}]
    data["phases"] = [
        {"lore": "one", "languages": base["languages"], "tests": base["tests"]},
        {"lore": "two", "languages": base["languages"], "tests": base["tests"],
         "limits": {"timeout_s": 3}},
    ]
    spec = parse_puzzle(data)
    assert spec.is_boss
    assert [p for p, _ in spec.bodies()] == [0, 1]
    assert spec.body_for(1).limits.timeout_s == 3
    assert spec.body_for(0).fixtures[0].path == "a.txt"
    with pytest.raises(IndexError):
        spec.body_for(2)
    with pytest.raises(IndexError):
        spec.body_for(None)


def test_load_puzzle_reports_bad_yaml(tmp_path: Path) -> None:
    bad = tmp_path / "bad.yaml"
    bad.write_text("id: [unclosed\n", encoding="utf-8")
    with pytest.raises(SpecError, match="not valid YAML"):
        load_puzzle(bad)


def test_load_all_rejects_duplicate_ids(tmp_path: Path) -> None:
    for name in ("a.yaml", "b.yaml"):
        (tmp_path / name).write_text(yaml.safe_dump(_minimal()), encoding="utf-8")
    with pytest.raises(SpecError, match="duplicate id"):
        load_all(tmp_path)


def test_json_is_accepted(tmp_path: Path) -> None:
    import json

    (tmp_path / "p.json").write_text(json.dumps(_minimal()), encoding="utf-8")
    assert "t-01" in load_all(tmp_path)


def test_shipped_content_loads() -> None:
    specs = load_all(CONTENT)
    assert {"ch0-01", "ch0-02", "ch0-03", "ch1-05"} <= set(specs)
    for spec in specs.values():
        assert spec.language_ids() == ["python", "bash", "powershell"]
    ferry = specs["ch1-05"]
    # YAML anchors are shared across languages.
    assert ferry.languages["python"].hints[0] == ferry.languages["bash"].hints[0]
    assert ferry.reward.items == ("ferry_token",)
    assert len(ferry.tests) == 3
