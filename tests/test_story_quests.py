"""Quest log step resolution, plus the bundled quests file."""

from coderogue.story.flags import Flags, apply_flags
from coderogue.story.quests import QuestLog, load_quests, parse_quests

DATA = [
    {"id": "a", "title": "First", "steps": [
        {"text": "one", "done_when": "f1"}, {"text": "two", "done_when": "f2"},
    ]},
    {"id": "b", "title": "Second", "starts_when": "go", "steps": [
        {"text": "three", "done_when": "f3"},
    ]},
]


def test_current_step_progression():
    flags = Flags()
    log = QuestLog(flags, parse_quests(DATA))
    assert log.current_quest.id == "a" and log.current_step_text == "one"
    flags.add("f2")  # out of order: step one still pending
    assert log.current_step_text == "one"
    flags.add("f1")
    assert log.current() is None  # quest b not started
    assert log.hud_text() == ""
    flags.add("go")
    assert log.hud_text() == "Second: three"
    flags.add("f3")
    assert log.current_quest is None and log.current_step_text == ""


def test_parse_wrapped_mapping():
    assert [q.id for q in parse_quests({"quests": DATA})] == ["a", "b"]


def test_bundled_quests_load():
    quests = load_quests()
    assert quests[0].id == "prologue"
    log = QuestLog(set(), quests)
    assert log.current_step_text.startswith("Talk to Pell")


def test_flags_helpers():
    f = Flags({"a"})
    assert f.has_all(["a"]) and not f.has_all(["a", "b"]) and f.has_any(["b", "a"])
    f.set_all(["b"])
    assert "b" in f
    target: list[str] = ["x"]
    apply_flags(target, ["x", "y"])
    assert target == ["x", "y"]
