"""JSON save profiles, with each spell draft as its own file and an optional git Ledger.

Layout (``root`` is the per-user data dir, see :func:`default_root`)::

    root/profiles/<slot>/save.json            # SaveState minus the drafts
    root/profiles/<slot>/spells/<id>.<ext>    # one file per puzzle per language
                                              # (boss phases: <id>__<phase>.<ext>)
    root/profiles/<slot>/.git                 # the Ledger (if git is available)

Keeping drafts as real files makes ``git diff`` show the player's code, line by line.

The game passes ``Progress.to_dict()`` as :attr:`SaveState.progress` and rebuilds with
``Progress.from_dict(state.progress)``; this module never imports ``coderogue.progress``.
If that dict has a ``"drafts"`` mapping of ``{puzzle_id: {language: source}}`` it is
written to ``spells/`` and, on load, refreshed from those files (so a Ledger restore wins).
"""

from __future__ import annotations

import json
import logging
import os
import re
import shutil
import sys
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from coderogue.save.gitstore import GitLedger, ledger_status

log = logging.getLogger(__name__)

SCHEMA_VERSION = 1
SAVE_FILE = "save.json"
SPELLS_DIR = "spells"
DEFAULT_SLOT = "slot1"
#: Language id -> spell file extension.
LANG_EXT: dict[str, str] = {"python": "py", "bash": "sh", "powershell": "ps1"}
#: A boss phase draft is keyed ``<puzzle_id>#<phase>``; on disk the ``#`` becomes this.
PHASE_FILE_SEP = "__"
_SLOT_RE = re.compile(r"^[A-Za-z0-9_-]{1,32}$")


def default_root() -> Path:
    """Per-user data directory (``CODEROGUE_HOME`` overrides it, e.g. in tests)."""
    override = os.environ.get("CODEROGUE_HOME")
    if override:
        return Path(override)
    home = Path.home()
    if sys.platform == "darwin":
        return home / "Library" / "Application Support" / "CodeRogue"
    if sys.platform.startswith("win"):
        appdata = os.environ.get("APPDATA")
        return (Path(appdata) if appdata else home / "AppData" / "Roaming") / "CodeRogue"
    xdg = os.environ.get("XDG_DATA_HOME")
    return (Path(xdg) if xdg else home / ".local" / "share") / "coderogue"


def lang_ext(language: str) -> str:
    """File extension for a language id (unknown ids use the id itself)."""
    return LANG_EXT.get(language, re.sub(r"[^A-Za-z0-9]", "", language) or "txt")


def ext_lang(ext: str) -> str:
    """Inverse of :func:`lang_ext`."""
    for lang, e in LANG_EXT.items():
        if e == ext:
            return lang
    return ext


def atomic_write_text(path: Path, text: str) -> None:
    """Write ``text`` to ``path`` via a temp file in the same dir and ``os.replace``."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as fh:
            fh.write(text)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


@dataclass
class PlayerState:
    """Where Wren stands."""

    x: float = 0.0
    y: float = 0.0
    hp: int = 5
    facing: str = "down"
    coins: int = 0
    hearts_max: int = 3
    u_charges: int = 3

    def to_dict(self) -> dict[str, Any]:
        """JSON-ready dict."""
        return {
            "x": self.x, "y": self.y, "hp": self.hp, "facing": self.facing,
            "coins": self.coins, "hearts_max": self.hearts_max, "u_charges": self.u_charges,
        }

    @classmethod
    def from_dict(cls, raw: dict[str, Any] | None) -> PlayerState:
        """Tolerant inverse of :meth:`to_dict`."""
        raw = raw or {}
        return cls(
            x=float(raw.get("x", 0.0)),
            y=float(raw.get("y", 0.0)),
            hp=int(raw.get("hp", 5)),
            facing=str(raw.get("facing", "down")),
            coins=int(raw.get("coins", 0)),
            hearts_max=int(raw.get("hearts_max", 3)),
            u_charges=int(raw.get("u_charges", 3)),
        )


@dataclass
class SaveState:
    """Everything a save slot holds.

    ``progress`` is ``Progress.to_dict()`` (kept as a plain dict on purpose). ``flags`` is
    for story flags not already inside progress. ``spells`` maps puzzle id -> language ->
    source; when empty, ``progress["drafts"]`` is used instead.
    """

    map: str = ""
    player: PlayerState = field(default_factory=PlayerState)
    progress: dict[str, Any] = field(default_factory=dict)
    flags: list[str] = field(default_factory=list)
    area_name: str = ""
    waystone: str = ""
    spells: dict[str, dict[str, str]] = field(default_factory=dict)
    saved_at: str = ""
    schema_version: int = SCHEMA_VERSION

    def drafts(self) -> dict[str, dict[str, str]]:
        """The drafts to write as spell files."""
        if self.spells:
            return self.spells
        raw = self.progress.get("drafts")
        if not isinstance(raw, dict):
            return {}
        out: dict[str, dict[str, str]] = {}
        for pid, by_lang in raw.items():
            if isinstance(by_lang, dict):
                out[str(pid)] = {str(k): v for k, v in by_lang.items() if isinstance(v, str)}
        return out

    def to_json(self) -> dict[str, Any]:
        """The ``save.json`` payload (drafts live in ``spells/``, not here)."""
        progress = {k: v for k, v in self.progress.items() if k != "drafts"}
        return {
            "schema_version": self.schema_version,
            "saved_at": self.saved_at,
            "map": self.map,
            "player": self.player.to_dict(),
            "progress": progress,
            "flags": sorted(set(self.flags)),
            "area_name": self.area_name,
            "waystone": self.waystone,
        }

    @classmethod
    def from_json(cls, raw: dict[str, Any]) -> SaveState:
        """Build from a ``save.json`` payload."""
        progress = raw.get("progress")
        return cls(
            map=str(raw.get("map", "")),
            player=PlayerState.from_dict(raw.get("player")),
            progress=dict(progress) if isinstance(progress, dict) else {},
            flags=[str(f) for f in raw.get("flags", []) or []],
            area_name=str(raw.get("area_name", "")),
            waystone=str(raw.get("waystone", "")),
            saved_at=str(raw.get("saved_at", "")),
            schema_version=int(raw.get("schema_version", SCHEMA_VERSION)),
        )


@dataclass(frozen=True)
class SaveReceipt:
    """What :meth:`SaveStore.save` did. ``sha`` is None when the Ledger did not commit."""

    slot: str
    path: Path
    saved_at: str
    message: str
    sha: str | None = None


@dataclass(frozen=True)
class SlotInfo:
    """Summary of a slot for a load menu."""

    slot: str
    saved_at: str
    area_name: str
    waystone: str


class SaveStore:
    """Save profiles under ``root/profiles/<slot>/``."""

    def __init__(self, root: Path | None = None, ledger_enabled: bool = True) -> None:
        self.root = Path(root) if root is not None else default_root()
        self.ledger_enabled = ledger_enabled

    # ---- paths ------------------------------------------------------------------------
    @property
    def profiles_dir(self) -> Path:
        """Directory containing one folder per slot."""
        return self.root / "profiles"

    def slot_dir(self, slot: str) -> Path:
        """Directory for ``slot`` (validated: letters, digits, ``_`` and ``-``)."""
        if not _SLOT_RE.match(slot):
            raise ValueError(f"invalid save slot name: {slot!r}")
        return self.profiles_dir / slot

    def ledger(self, slot: str) -> GitLedger:
        """The git Ledger for ``slot``."""
        return GitLedger(self.slot_dir(slot), enabled=self.ledger_enabled)

    def ledger_status(self) -> str:
        """``"Ledger: on (git 2.x)"`` / ``"Ledger: off"`` / ``"Ledger: git not found"``."""
        return ledger_status(self.ledger_enabled)

    # ---- API --------------------------------------------------------------------------
    def save(self, slot: str, state: SaveState, message: str | None = None) -> SaveReceipt:
        """Write ``state`` atomically, then seal it in the Ledger if git is available."""
        directory = self.slot_dir(slot)
        state.saved_at = time.strftime("%Y-%m-%dT%H:%M:%S%z")
        self._write_spells(directory / SPELLS_DIR, state.drafts())
        path = directory / SAVE_FILE
        atomic_write_text(path, json.dumps(state.to_json(), indent=2, sort_keys=True) + "\n")
        msg = message or f"Sealed at {state.waystone or state.area_name or 'the road'}"
        sha = None
        ledger = self.ledger(slot)
        if ledger.available:
            sha = ledger.commit(msg)
        return SaveReceipt(slot, path, state.saved_at, msg, sha)

    def load(self, slot: str) -> SaveState | None:
        """Read ``slot``; None if it does not exist or is unreadable."""
        directory = self.slot_dir(slot)
        try:
            raw = json.loads((directory / SAVE_FILE).read_text(encoding="utf-8"))
        except FileNotFoundError:
            return None
        except (OSError, ValueError) as exc:
            log.warning("save: cannot read slot %s: %s", slot, exc)
            return None
        if not isinstance(raw, dict):
            return None
        state = SaveState.from_json(raw)
        state.spells = self._read_spells(directory / SPELLS_DIR)
        if state.spells:
            state.progress["drafts"] = {k: dict(v) for k, v in state.spells.items()}
        return state

    def exists(self, slot: str) -> bool:
        """True when ``slot`` has a save file."""
        return (self.slot_dir(slot) / SAVE_FILE).is_file()

    def list_slots(self) -> list[SlotInfo]:
        """Slots that have a save, newest first."""
        if not self.profiles_dir.is_dir():
            return []
        infos = []
        for child in self.profiles_dir.iterdir():
            if not child.is_dir() or not _SLOT_RE.match(child.name):
                continue
            try:
                raw = json.loads((child / SAVE_FILE).read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            if isinstance(raw, dict):
                infos.append(SlotInfo(
                    child.name, str(raw.get("saved_at", "")),
                    str(raw.get("area_name", "")), str(raw.get("waystone", "")),
                ))
        infos.sort(key=lambda i: i.saved_at, reverse=True)
        return infos

    def delete(self, slot: str) -> bool:
        """Remove a slot (and its Ledger). Returns True if something was deleted."""
        directory = self.slot_dir(slot)
        if not directory.exists():
            return False
        shutil.rmtree(directory)
        return True

    def tag_chapter(self, slot: str, name: str) -> bool:
        """Tag the latest seal, e.g. ``tag_chapter("slot1", "ch1")`` after a boss."""
        ledger = self.ledger(slot)
        return ledger.available and ledger.initialized and ledger.tag(name)

    # ---- spells -----------------------------------------------------------------------
    @staticmethod
    def spell_name(puzzle_id: str, language: str) -> str:
        """File name of a draft, e.g. ``ch0-01.py`` (boss phase ``ch1-b#1`` -> ``ch1-b__1.py``)."""
        safe = re.sub(r"[^A-Za-z0-9_.-]", "_", puzzle_id.replace("#", PHASE_FILE_SEP))
        return f"{safe}.{lang_ext(language)}"

    def spell_path(self, slot: str, puzzle_id: str, language: str) -> Path:
        """Absolute path of one draft file."""
        return self.slot_dir(slot) / SPELLS_DIR / self.spell_name(puzzle_id, language)

    def _write_spells(self, spells_dir: Path, drafts: dict[str, dict[str, str]]) -> None:
        for pid, by_lang in drafts.items():
            for language, source in by_lang.items():
                atomic_write_text(spells_dir / self.spell_name(pid, language), source)

    @staticmethod
    def _read_spells(spells_dir: Path) -> dict[str, dict[str, str]]:
        out: dict[str, dict[str, str]] = {}
        if not spells_dir.is_dir():
            return out
        for path in sorted(spells_dir.iterdir()):
            if not path.is_file() or path.name.startswith(".") or "." not in path.name:
                continue
            pid, _, ext = path.name.rpartition(".")
            pid = pid.replace(PHASE_FILE_SEP, "#")
            try:
                source = path.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                continue
            out.setdefault(pid, {})[ext_lang(ext)] = source
        return out
