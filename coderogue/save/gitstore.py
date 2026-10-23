"""The Ledger: an optional git history of a save profile.

In the fiction, a scribe "sets a seal" at a waystone; under the hood that is a real
``git commit`` in the profile directory, so players meet version control by name. Every
command and its output are kept on :attr:`GitLedger.last_command` / :attr:`last_output` so
the Ledger UI can show exactly what ran.

Nothing here ever raises on git trouble: if git is missing, disabled or fails, methods log
and return ``None`` / empty values, and the game carries on with plain files.
"""

from __future__ import annotations

import logging
import os
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

log = logging.getLogger(__name__)

GIT_TIMEOUT = 10.0
LEDGER_USER = "Wren"
LEDGER_EMAIL = "wren@shellmarch.invalid"
GITIGNORE = "# Written by CodeRogue.\n*.tmp\n.*.tmp\n__pycache__/\n"
_FIELD_SEP = "\x1f"


@dataclass(frozen=True)
class LedgerEntry:
    """One sealed save: abbreviated sha, ISO-8601 commit time and the message subject."""

    sha: str
    when: str
    message: str


def git_executable() -> str | None:
    """Path to ``git`` on PATH, or None."""
    return shutil.which("git")


def git_version() -> str | None:
    """Version string such as ``"2.44.0"``, or None if git is missing or broken."""
    exe = git_executable()
    if exe is None:
        return None
    try:
        proc = subprocess.run(
            [exe, "--version"], capture_output=True, text=True, timeout=GIT_TIMEOUT,
            env=_git_env(),
        )
    except (OSError, subprocess.SubprocessError):
        return None
    m = re.search(r"(\d+(?:\.\d+)+)", proc.stdout)
    return m.group(1) if m else None


def ledger_status(enabled: bool = True) -> str:
    """One-line status for the settings screen."""
    if not enabled:
        return "Ledger: off"
    version = git_version()
    if version is None:
        return "Ledger: git not found"
    return f"Ledger: on (git {version})"


def _git_env() -> dict[str, str]:
    """A small, predictable environment: no prompts, no user hooks/config surprises."""
    env = {k: os.environ[k] for k in ("PATH", "HOME", "SYSTEMROOT", "TMPDIR") if k in os.environ}
    env.update(
        GIT_TERMINAL_PROMPT="0",
        LC_ALL="C",
        GIT_CONFIG_NOSYSTEM="1",
        GIT_AUTHOR_NAME=LEDGER_USER,
        GIT_AUTHOR_EMAIL=LEDGER_EMAIL,
        GIT_COMMITTER_NAME=LEDGER_USER,
        GIT_COMMITTER_EMAIL=LEDGER_EMAIL,
    )
    return env


class GitLedger:
    """git operations on one profile directory. Safe to use when git is absent."""

    def __init__(self, repo_dir: str | Path, enabled: bool = True) -> None:
        self.repo_dir = Path(repo_dir)
        self.enabled = enabled
        self.last_command: list[str] = []
        self.last_output: str = ""
        self.last_ok: bool = False

    # ---- plumbing ---------------------------------------------------------------------
    @property
    def available(self) -> bool:
        """True when the Ledger is switched on and git is installed."""
        return self.enabled and git_executable() is not None

    @property
    def initialized(self) -> bool:
        """True when ``repo_dir`` already holds a git repository."""
        return (self.repo_dir / ".git").exists()

    def _run(self, *args: str) -> str | None:
        """Run ``git <args>`` in the repo. Returns stdout on success, else None (logged)."""
        self.last_command = ["git", *args]
        self.last_ok = False
        if not self.available:
            self.last_output = "Ledger unavailable."
            return None
        exe = git_executable()
        assert exe is not None
        try:
            proc = subprocess.run(
                [exe, *args],
                cwd=self.repo_dir,
                capture_output=True,
                text=True,
                timeout=GIT_TIMEOUT,
                env=_git_env(),
            )
        except (OSError, subprocess.SubprocessError) as exc:
            self.last_output = f"{type(exc).__name__}: {exc}"
            log.warning("ledger: %s failed: %s", " ".join(self.last_command), exc)
            return None
        self.last_output = (proc.stdout + proc.stderr).rstrip("\n")
        if proc.returncode != 0:
            log.warning(
                "ledger: %s exited %d: %s", " ".join(self.last_command), proc.returncode,
                proc.stderr.strip(),
            )
            return None
        self.last_ok = True
        return proc.stdout

    # ---- public API -------------------------------------------------------------------
    def init(self) -> bool:
        """Create the repository (idempotent). Returns True when the repo is ready."""
        if not self.available:
            return False
        try:
            self.repo_dir.mkdir(parents=True, exist_ok=True)
            ignore = self.repo_dir / ".gitignore"
            if not ignore.exists():
                ignore.write_text(GITIGNORE, encoding="utf-8")
        except OSError as exc:
            log.warning("ledger: cannot prepare %s: %s", self.repo_dir, exc)
            return False
        if not self.initialized and self._run("init", "-q") is None:
            return False
        ok = self._run("config", "user.name", LEDGER_USER) is not None
        ok = ok and self._run("config", "user.email", LEDGER_EMAIL) is not None
        ok = ok and self._run("config", "commit.gpgsign", "false") is not None
        return ok

    def commit(self, message: str) -> str | None:
        """Stage everything and commit (empty commits allowed). Returns the short sha."""
        if not self.available:
            return None
        if not self.initialized and not self.init():
            return None
        if self._run("add", "-A") is None:
            return None
        if self._run("commit", "--allow-empty", "--no-verify", "-q", "-m", message) is None:
            return None
        command, output = self.last_command, self.last_output
        sha = self._run("rev-parse", "--short", "HEAD")
        # Show the user the commit, not the rev-parse bookkeeping.
        self.last_command, self.last_output = command, output or (sha or "").strip()
        return sha.strip() if sha else None

    def tag(self, name: str) -> bool:
        """Point tag ``name`` at HEAD (moved if it already exists)."""
        return self._run("tag", "-f", name) is not None

    def tags(self) -> list[str]:
        """All tag names."""
        out = self._run("tag", "--list")
        return out.split() if out else []

    def log(self, limit: int = 20) -> list[LedgerEntry]:
        """Newest-first history, at most ``limit`` entries."""
        fmt = _FIELD_SEP.join(("%h", "%cI", "%s"))
        out = self._run("log", f"-n{int(limit)}", f"--format={fmt}")
        if not out:
            return []
        entries = []
        for line in out.splitlines():
            parts = line.split(_FIELD_SEP)
            if len(parts) == 3:
                entries.append(LedgerEntry(*parts))
        return entries

    def diff(self, path: str | None = None) -> str:
        """Uncommitted changes against the last seal (whole repo, or one ``path``)."""
        args = ["diff", "--no-color", "HEAD"]
        if path is not None:
            args += ["--", path]
        return self._run(*args) or ""

    def restore(self, path: str, sha: str = "HEAD") -> bool:
        """Bring ``path`` back as it was at ``sha`` (``git checkout <sha> -- <path>``)."""
        return self._run("checkout", sha, "--", path) is not None

    def show_file(self, path: str, sha: str) -> str:
        """Contents of ``path`` at commit ``sha`` (empty string if unavailable)."""
        return self._run("show", f"{sha}:{path}") or ""
