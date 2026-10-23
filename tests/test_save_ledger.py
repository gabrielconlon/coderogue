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


# ---- review fixes: config isolation, encoding, stale locks, option injection ---------------

def _hostile_home(tmp_path):
    """A HOME whose global git config runs a hook and demands signed tags/commits."""
    home = tmp_path / "home"
    hooks = home / "hooks"
    hooks.mkdir(parents=True)
    ran = tmp_path / "hook-ran"
    for name in ("pre-commit", "post-commit", "commit-msg", "reference-transaction"):
        hook = hooks / name
        hook.write_text(f"#!/bin/sh\necho {name} >> '{ran}'\nexit 1\n")
        hook.chmod(0o755)
    (home / ".gitconfig").write_text(
        f"[core]\n\thooksPath = {hooks}\n[commit]\n\tgpgSign = true\n"
        "[tag]\n\tgpgSign = true\n\tforceSignAnnotated = true\n"
        "[gpg]\n\tprogram = /nonexistent/gpg\n[user]\n\tsigningkey = DEADBEEF\n"
    )
    xdg = home / ".config" / "git"
    xdg.mkdir(parents=True)
    (xdg / "config").write_text(f"[core]\n\thooksPath = {hooks}\n")
    return home, ran


@needs_git
def test_global_git_config_does_not_leak_in(tmp_path, monkeypatch):
    home, ran = _hostile_home(tmp_path)
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(home / ".config"))
    ledger = GitLedger(tmp_path / "repo")
    assert ledger.init()
    (tmp_path / "repo" / "a.txt").write_text("a\n")
    sha = ledger.commit("Sealed")
    assert sha, ledger.last_error
    assert ledger.tag("ch1"), ledger.last_error
    assert "ch1" in ledger.tags()
    assert not ran.exists(), ran.read_text()
    # What the player sees in the Ledger UI is the plain command, not the -c plumbing.
    assert ledger.last_command == ["git", "tag", "--list"]
    env = gitstore._git_env()
    assert env["GIT_CONFIG_GLOBAL"] == env["GIT_CONFIG_SYSTEM"] == gitstore.os.devnull


@needs_git
def test_output_is_utf8_regardless_of_locale(tmp_path, monkeypatch):
    seen = {}
    real_run = gitstore.subprocess.run

    def spy(*a, **k):
        seen.update(k)
        return real_run(*a, **k)

    monkeypatch.setattr(gitstore.subprocess, "run", spy)
    ledger = GitLedger(tmp_path / "repo")
    ledger.init()
    assert ledger.commit("Sealed at Ćaer Wrén ✓")
    assert ledger.log()[0].message == "Sealed at Ćaer Wrén ✓"
    assert seen["encoding"] == "utf-8" and seen["errors"] == "replace"


@needs_git
def test_stale_index_lock_is_cleared_and_fresh_one_reported(tmp_path, monkeypatch):
    import os
    import time

    monkeypatch.setenv("CODEROGUE_HOME", str(tmp_path))
    store = SaveStore()
    state = SaveState(map="m.tmj", waystone="Tilde Square")
    assert store.save("slot1", state).sha
    lock = store.slot_dir("slot1") / ".git" / "index.lock"

    # A lock left by a git that was killed long ago: removed, the seal works.
    lock.write_text("")
    old = time.time() - 3600
    os.utime(lock, (old, old))
    r = store.save("slot1", state)
    assert r.sha and r.error is None
    assert not lock.exists()

    # A fresh lock (another git may be running): left alone, and the reason surfaces.
    lock.write_text("")
    r = store.save("slot1", state)
    assert r.sha is None
    assert r.error and "index.lock" in r.error
    assert store.ledger("slot1").commit("x") is None
    lock.unlink()


@needs_git
def test_option_like_names_are_refused(tmp_path):
    ledger = GitLedger(tmp_path / "repo")
    ledger.init()
    (tmp_path / "repo" / "a.txt").write_text("a\n")
    assert ledger.commit("one")
    assert ledger.tag("--help") is False
    assert ledger.last_error and "cannot start with '-'" in ledger.last_error
    assert ledger.restore("a.txt", "--orphan=x") is False
    assert ledger.show_file("a.txt", "--output=/tmp/pwned") == ""
    assert ledger.tags() == []
