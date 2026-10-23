"""SaveStore: round trips, spell files, atomic writes, slot listing."""

import json
import os
from pathlib import Path

import pytest

from coderogue.save import store as store_mod
from coderogue.save.store import PlayerState, SaveState, SaveStore, atomic_write_text, default_root


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("CODEROGUE_HOME", str(tmp_path / "home"))
    return tmp_path / "home"


def sample_state() -> SaveState:
    return SaveState(
        map="content/maps/test_room.tmj",
        player=PlayerState(x=40.5, y=88.0, hp=4, facing="left"),
        progress={
            "solved": ["ch0-01"],
            "xp": 30,
            "flags": ["met:pell"],
            "drafts": {"ch0-01": {"python": 'print("Hello, Tilde.")\n', "bash": "echo hi\n"}},
        },
        flags=["got_ink", "met:pell"],
        area_name="Little Tilde",
        waystone="Tilde Square",
    )


def test_default_root_honours_env(home):
    assert default_root() == home
    assert SaveStore().root == home


def test_default_root_platforms(monkeypatch, tmp_path):
    monkeypatch.delenv("CODEROGUE_HOME", raising=False)
    monkeypatch.setattr(store_mod.Path, "home", lambda: tmp_path)
    monkeypatch.setattr(store_mod.sys, "platform", "darwin")
    assert default_root() == tmp_path / "Library" / "Application Support" / "CodeRogue"
    monkeypatch.setattr(store_mod.sys, "platform", "linux")
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "xdg"))
    assert default_root() == tmp_path / "xdg" / "coderogue"
    monkeypatch.setattr(store_mod.sys, "platform", "win32")
    monkeypatch.setenv("APPDATA", str(tmp_path / "ad"))
    assert default_root() == tmp_path / "ad" / "CodeRogue"


def test_round_trip_without_git(home):
    store = SaveStore(ledger_enabled=False)
    receipt = store.save("slot1", sample_state())
    assert receipt.sha is None
    assert receipt.message == "Sealed at Tilde Square"
    loaded = store.load("slot1")
    assert loaded is not None
    assert loaded.map == "content/maps/test_room.tmj"
    assert loaded.player == PlayerState(40.5, 88.0, 4, "left")
    assert loaded.area_name == "Little Tilde" and loaded.waystone == "Tilde Square"
    assert set(loaded.flags) == {"got_ink", "met:pell"}
    assert loaded.progress["xp"] == 30
    assert loaded.progress["drafts"]["ch0-01"]["python"] == 'print("Hello, Tilde.")\n'
    assert loaded.spells["ch0-01"]["bash"] == "echo hi\n"
    assert loaded.saved_at and loaded.schema_version == 1


def test_spells_are_files_and_not_in_json(home):
    store = SaveStore(ledger_enabled=False)
    store.save("slot1", sample_state())
    slot = home / "profiles" / "slot1"
    assert (slot / "spells" / "ch0-01.py").read_text() == 'print("Hello, Tilde.")\n'
    assert (slot / "spells" / "ch0-01.sh").read_text() == "echo hi\n"
    raw = json.loads((slot / "save.json").read_text())
    assert "drafts" not in raw["progress"]
    assert set(raw) >= {"schema_version", "saved_at", "map", "player", "progress", "flags"}
    assert store.spell_path("slot1", "ch0-01", "python") == slot / "spells" / "ch0-01.py"


def test_load_missing_and_corrupt(home):
    store = SaveStore(ledger_enabled=False)
    assert store.load("nope") is None
    path = home / "profiles" / "bad" / "save.json"
    path.parent.mkdir(parents=True)
    path.write_text("{not json")
    assert store.load("bad") is None


def test_list_and_delete(home):
    store = SaveStore(ledger_enabled=False)
    assert store.list_slots() == []
    store.save("slot1", sample_state())
    store.save("slot2", sample_state())
    names = {s.slot for s in store.list_slots()}
    assert names == {"slot1", "slot2"}
    assert store.exists("slot1")
    assert store.delete("slot1") is True
    assert store.delete("slot1") is False
    assert [s.slot for s in store.list_slots()] == ["slot2"]


def test_invalid_slot_name(home):
    with pytest.raises(ValueError):
        SaveStore(ledger_enabled=False).slot_dir("../evil")


def test_atomic_write_leaves_old_file_on_failure(tmp_path, monkeypatch):
    target = tmp_path / "save.json"
    atomic_write_text(target, "old")

    def boom(src, dst):
        raise OSError("disk full")

    monkeypatch.setattr(store_mod.os, "replace", boom)
    with pytest.raises(OSError):
        atomic_write_text(target, "new and partial")
    assert target.read_text() == "old"
    assert [p.name for p in tmp_path.iterdir()] == ["save.json"]  # temp file cleaned up


def test_atomic_write_no_temp_left(tmp_path):
    target = tmp_path / "a" / "b.txt"
    atomic_write_text(target, "x")
    assert os.listdir(target.parent) == ["b.txt"]
    assert Path(target).read_text() == "x"
