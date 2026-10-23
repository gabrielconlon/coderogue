"""tools/fetch_assets.py and tools/fetch_runtime.py: the offline-testable safety logic."""

from __future__ import annotations

import importlib.util
import io
import zipfile
from pathlib import Path
from types import ModuleType

import pytest

TOOLS = Path(__file__).resolve().parent.parent / "tools"


def _load(name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(f"_tools_{name}", TOOLS / f"{name}.py")
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


fetch_assets = _load("fetch_assets")
fetch_runtime = _load("fetch_runtime")


def _zip(entries: dict[str, bytes]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for name, data in entries.items():
            zf.writestr(name, data)
    return buf.getvalue()


def test_install_zip_extracts_and_replaces(tmp_path: Path) -> None:
    dest = tmp_path / "kenney" / "tiny-town"
    fetch_assets.install_zip(_zip({"Tiles/a.png": b"a", "License.txt": b"cc0"}), dest)
    assert (dest / "Tiles" / "a.png").read_bytes() == b"a"
    fetch_assets.install_zip(_zip({"b.png": b"b"}), dest)
    assert sorted(p.name for p in dest.iterdir()) == ["b.png"]
    assert [p.name for p in dest.parent.iterdir()] == ["tiny-town"]  # no staging left


@pytest.mark.parametrize("evil", ["../escape.txt", "../tiny-town-evil/x.txt", "/abs.txt"])
def test_install_zip_refuses_traversal_and_leaves_nothing(tmp_path: Path, evil: str) -> None:
    dest = tmp_path / "kenney" / "tiny-town"
    with pytest.raises(RuntimeError, match="unsafe path"):
        fetch_assets.install_zip(_zip({"ok.txt": b"x", evil: b"y"}), dest)
    # A sibling whose name merely starts with the pack's name was the old startswith() hole.
    assert not dest.exists()
    assert list((tmp_path / "kenney").iterdir()) == []
    assert not (tmp_path / "escape.txt").exists()


def test_install_zip_failure_keeps_previous_pack(tmp_path: Path) -> None:
    dest = tmp_path / "pack"
    fetch_assets.install_zip(_zip({"old.txt": b"old"}), dest)
    with pytest.raises(zipfile.BadZipFile):
        fetch_assets.install_zip(b"not a zip", dest)
    assert (dest / "old.txt").read_bytes() == b"old"
    assert [p.name for p in tmp_path.iterdir()] == ["pack"]


def test_checksum_fails_closed(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit, match="allow-unverified"):
        fetch_runtime.check_checksum("py.tar.gz", "abc", None, allow_unverified=False)
    fetch_runtime.check_checksum("py.tar.gz", "abc", None, allow_unverified=True)
    assert "not verified" in capsys.readouterr().out
    with pytest.raises(SystemExit, match="mismatch"):
        fetch_runtime.check_checksum("py.tar.gz", "abc", "def", allow_unverified=True)
    fetch_runtime.check_checksum("py.tar.gz", "abc", "abc", allow_unverified=False)


def test_install_dir_replaces_only_after_move(tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    dest = tmp_path / "runtime" / "python"
    dest.mkdir(parents=True)
    (dest / "old").write_text("old")
    src = tmp_path / "new"
    src.mkdir()
    (src / "bin").write_text("new")
    fetch_runtime.install_dir(src, dest)
    assert sorted(p.name for p in dest.iterdir()) == ["bin"]
    assert [p.name for p in dest.parent.iterdir()] == ["python"]

    # A failed move puts the previous runtime back.
    src2 = tmp_path / "newer"
    src2.mkdir()

    def boom(a: str, b: object) -> None:
        raise OSError("disk full")

    monkeypatch.setattr(fetch_runtime.shutil, "move", boom)
    with pytest.raises(OSError):
        fetch_runtime.install_dir(src2, dest)
    assert (dest / "bin").read_text() == "new"
    assert [p.name for p in dest.parent.iterdir()] == ["python"]
