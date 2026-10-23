"""Dialogue bank: loading, pick with requires/unless/once, choices; bundled content."""

import textwrap

import pytest

from coderogue.app import resource_path
from coderogue.story.dialogue import Choice, DialogueBank, DialogueError

YAML = textwrap.dedent(
    """
    pell_late:
      npc: pell
      speaker: None
      requires: [null_came]
      lines: ["None."]
    pell_once:
      npc: pell
      speaker: Pell
      once: true
      requires: [met]
      lines: ["Only once."]
    pell_intro:
      npc: pell
      speaker: Pell
      unless: [met]
      sets: [met]
      lines: ["Hello.", "Second line."]
      choices:
        - {text: "Hi.", sets: [polite]}
        - "Plain choice"
    pell_idle:
      npc: pell
      speaker: Pell
      lines: ["Hm."]
    other:
      speaker: Sign
      lines: "Single string line"
    """
)


@pytest.fixture
def bank(tmp_path):
    (tmp_path / "a.yaml").write_text(YAML)
    return DialogueBank.load_dir(tmp_path)


def test_load_and_get(bank):
    d = bank.get("pell_intro")
    assert d.speaker == "Pell" and d.lines == ("Hello.", "Second line.")
    assert d.choices == (Choice("Hi.", ("polite",)), Choice("Plain choice"))
    assert bank.get("other").lines == ("Single string line",)
    assert [x.id for x in bank.for_npc("pell")] == [
        "pell_late", "pell_once", "pell_intro", "pell_idle"
    ]
    with pytest.raises(KeyError):
        bank.get("nope")


def test_pick_order_requires_unless_once(bank):
    flags: set[str] = set()
    assert bank.pick("pell", flags).id == "pell_intro"
    flags.update(bank.get("pell_intro").flags_on_finish())
    assert bank.pick("pell", flags).id == "pell_once"
    flags.update(bank.get("pell_once").flags_on_finish())
    assert "seen:pell_once" in flags
    assert bank.pick("pell", flags).id == "pell_idle"
    flags.add("null_came")
    assert bank.pick("pell", flags).id == "pell_late"
    assert bank.pick("nobody", flags) is None


def test_flags_on_finish_with_choice(bank):
    d = bank.get("pell_intro")
    assert d.flags_on_finish(d.choices[0]) == ["met", "polite"]


def test_bad_files(tmp_path):
    (tmp_path / "x.yaml").write_text("a: {speaker: X}\n")
    with pytest.raises(DialogueError):
        DialogueBank.load_dir(tmp_path)
    (tmp_path / "x.yaml").write_text("- just a list\n")
    with pytest.raises(DialogueError):
        DialogueBank.load_dir(tmp_path)
    assert DialogueBank.load_dir(tmp_path / "missing").entries == {}


def test_bundled_little_tilde_walkthrough():
    bank = DialogueBank.load_dir(resource_path("content", "dialogue"))
    flags: set[str] = set()

    def talk(npc: str, choice: int | None = None) -> str:
        d = bank.pick(npc, flags)
        assert d is not None, npc
        flags.update(d.flags_on_finish(d.choices[choice] if choice is not None else None))
        return d.id

    assert talk("pell") == "pell_intro"
    assert "met:pell" in flags
    assert talk("pell") == "pell_ink_reminder"
    assert talk("ink_shelf") == "ink_shelf"
    assert talk("pell") == "pell_strike"
    assert talk("moth", 0) == "moth_intro"
    assert talk("moth") == "moth_after"
    assert talk("pell") == "pell_warning"
    assert talk("pell") == "pell_nulled"
    assert bank.pick("pell", flags).lines[0] == "None."
    assert talk("quill_echo") == "quill_echo"
    assert bank.pick("cole", flags) is None
    flags.update({"solved:ch0-01", "solved:ch0-02", "solved:ch0-03"})
    cole = bank.pick("cole", flags)
    assert any("git commit" in line for line in cole.lines)
    assert any(":help" in line for line in cole.lines)
    assert talk("cole") == "cole_intro"
    assert "ledger_unlocked" in flags
    assert talk("cole") == "cole_after"
