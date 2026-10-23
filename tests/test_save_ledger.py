"""GitLedger against a real git, and graceful degradation without one."""

import shutil

import pytest

from coderogue.save import gitstore
from coderogue.save.gitstore import GitLedger, ledger_status
from coderogue.save.store import PlayerState, SaveState, SaveStore

needs_git = pytest.mark.skipif(shutil.which("git") is None, reason="git not installed")


@needs_git
def test_init_commit_log_diff_restore_tag(tmp_path):
    ledger = GitLedger(tmp_path / "repo")
    assert ledger.available
    assert ledger.init()
    assert (tmp_path / "repo" / ".gitignore").exists()
    spell = tmp_path / "repo" / "spells" / "ch0-01.py"
    spell.parent.mkdir()
    spell.write_text('print("Hello, Tilde.")\n')

    sha = ledger.commit("Sealed at Tilde Square")
    assert sha and len(sha) >= 4
    assert ledger.last_command[:2] == ["git", "commit"]
    entries = ledger.log()
    assert entries[0].sha == sha and entries[0].message == "Sealed at Tilde Square"
    assert entries[0].when

    spell.write_text('print("Goodbye")\n')
    diff = ledger.diff("spells/ch0-01.py")
    assert '-print("Hello, Tilde.")' in diff and '+print("Goodbye")' in diff
    assert ledger.last_command == ["git", "diff", "--no-color", "HEAD", "--", "spells/ch0-01.py"]
    assert "Goodbye" in ledger.last_output

    assert ledger.restore("spells/ch0-01.py")
    assert spell.read_text() == 'print("Hello, Tilde.")\n'
    assert ledger.diff() == ""

    assert ledger.tag("ch0")
    assert "ch0" in ledger.tags()
    assert ledger.show_file("spells/ch0-01.py", sha) == 'print("Hello, Tilde.")\n'

    sha2 = ledger.commit("Nothing changed")  # --allow-empty
    assert sha2 and sha2 != sha
    assert len(ledger.log(limit=1)) == 1


@needs_git
def test_failures_return_none_and_never_raise(tmp_path):
    ledger = GitLedger(tmp_path / "repo")
    ledger.init()
    assert ledger.show_file("missing.txt", "HEAD") == ""
    assert ledger.restore("missing.txt", "deadbeef") is False
    assert ledger.last_command[:2] == ["git", "checkout"]
    assert ledger.last_output  # git's error text is kept for the UI


@needs_git
def test_store_commits_and_tags(tmp_path, monkeypatch):
    monkeypatch.setenv("CODEROGUE_HOME", str(tmp_path))
    store = SaveStore()
    state = SaveState(
        map="m.tmj", player=PlayerState(1, 2), area_name="Little Tilde", waystone="Tilde Square",
        spells={"ch0-01": {"python": "print(1)\n"}},
    )
    r1 = store.save("slot1", state)
    assert r1.sha
    state.spells["ch0-01"]["python"] = "print(2)\n"
    r2 = store.save("slot1", state, message="Second seal")
    assert r2.sha and r2.sha != r1.sha
    ledger = store.ledger("slot1")
    assert [e.message for e in ledger.log()] == ["Second seal", "Sealed at Tilde Square"]
    assert store.tag_chapter("slot1", "ch1")
    assert "ch1" in ledger.tags()
    assert ledger.show_file("spells/ch0-01.py", r1.sha) == "print(1)\n"
    assert ledger.restore("spells/ch0-01.py", r1.sha)
    loaded = store.load("slot1")
    assert loaded is not None and loaded.spells["ch0-01"]["python"] == "print(1)\n"
    assert store.ledger_status().startswith("Ledger: on (git ")


def test_disabled_ledger_degrades(tmp_path):
    ledger = GitLedger(tmp_path, enabled=False)
    assert not ledger.available
    assert ledger.init() is False
    assert ledger.commit("x") is None
    assert ledger.log() == []
    assert ledger.diff() == ""
    assert ledger.tag("t") is False
    assert ledger_status(enabled=False) == "Ledger: off"


def test_missing_git_degrades(tmp_path, monkeypatch):
    monkeypatch.setattr(gitstore.shutil, "which", lambda name: None)
    monkeypatch.setenv("CODEROGUE_HOME", str(tmp_path))
    ledger = GitLedger(tmp_path)
    assert not ledger.available
    assert ledger.commit("x") is None
    assert ledger.restore("a") is False
    assert ledger.show_file("a", "HEAD") == ""
    assert ledger_status() == "Ledger: git not found"
    store = SaveStore()
    receipt = store.save("slot1", SaveState(map="m.tmj"))
    assert receipt.sha is None
    assert store.load("slot1") is not None
    assert store.tag_chapter("slot1", "ch1") is False
    assert not (tmp_path / "profiles" / "slot1" / ".git").exists()


def test_subprocess_error_is_swallowed(tmp_path, monkeypatch):
    monkeypatch.setattr(gitstore.shutil, "which", lambda name: "/usr/bin/git")

    def explode(*a, **k):
        raise OSError("no such file")

    monkeypatch.setattr(gitstore.subprocess, "run", explode)
    ledger = GitLedger(tmp_path)
    assert ledger.commit("x") is None
    assert "OSError" in ledger.last_output or ledger.last_output == ""
    assert ledger_status() == "Ledger: git not found"
