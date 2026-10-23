"""Packaging: resource lookup when frozen, the Python fallback chain, and the build spec."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

from coderogue import app
from coderogue.languages import python as pylang
from coderogue.languages.python import PythonLanguage

REPO = Path(__file__).resolve().parent.parent


def _freeze(monkeypatch: pytest.MonkeyPatch, meipass: Path) -> None:
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "_MEIPASS", str(meipass), raising=False)


def test_resource_path_dev_is_repo_root(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delattr(sys, "_MEIPASS", raising=False)
    assert app.resource_path("content", "quests.yaml") == REPO / "content" / "quests.yaml"
    assert app.resource_path(*app.DEFAULT_MAP).is_file()


def test_resource_path_frozen_uses_meipass(monkeypatch, tmp_path: Path) -> None:
    # --add-data "content:content" lands at <_MEIPASS>/content
    (tmp_path / "content" / "maps").mkdir(parents=True)
    _freeze(monkeypatch, tmp_path)
    assert app.resource_path("content", "maps") == tmp_path / "content" / "maps"
    assert app.resource_path("assets", "kenney") == tmp_path / "assets" / "kenney"
    assert app.resource_path() == tmp_path
    assert app._resolve_map(None) == tmp_path.joinpath(*app.DEFAULT_MAP)


def _fake_runtime(root: Path) -> Path:
    rel = "python.exe" if sys.platform == "win32" else "bin/python3"
    exe = root / "runtime" / "python" / rel
    exe.parent.mkdir(parents=True)
    exe.write_text("")
    exe.chmod(0o755)
    return exe


def test_bundled_python_found_under_meipass(monkeypatch, tmp_path: Path) -> None:
    _freeze(monkeypatch, tmp_path)
    assert pylang.bundled_python() is None
    exe = _fake_runtime(tmp_path)
    assert pylang.bundled_python() == str(exe)


def _probe_versions(monkeypatch, versions: dict[str, str]) -> None:
    """Make ``<exe> --version`` answer from ``versions`` (missing exe: cannot run)."""

    def fake_run_probe(argv, timeout=5.0):
        return versions.get(argv[0])

    monkeypatch.setattr(pylang, "run_probe", fake_run_probe)


def test_frozen_prefers_bundled_runtime(monkeypatch, tmp_path: Path) -> None:
    _freeze(monkeypatch, tmp_path)
    exe = str(_fake_runtime(tmp_path))
    monkeypatch.setattr(pylang, "_path_candidates", lambda: ["/somewhere/python3"])
    _probe_versions(monkeypatch, {exe: "Python 3.13.17", "/somewhere/python3": "Python 3.12.1"})
    rt = PythonLanguage().detect()
    assert rt is not None and rt.executable == exe and rt.version == (3, 13, 17)


def test_frozen_falls_back_to_path_and_skips_old_pythons(monkeypatch, tmp_path: Path) -> None:
    _freeze(monkeypatch, tmp_path)
    monkeypatch.setattr(pylang, "_path_candidates", lambda: ["/usr/bin/python3", "/opt/py3"])
    _probe_versions(monkeypatch, {"/usr/bin/python3": "Python 3.9.6", "/opt/py3": "Python 3.12.4"})
    rt = PythonLanguage().detect()
    assert rt is not None and rt.executable == "/opt/py3"


def test_frozen_without_any_python_greys_out(monkeypatch, tmp_path: Path) -> None:
    _freeze(monkeypatch, tmp_path)
    monkeypatch.setattr(pylang, "_path_candidates", lambda: ["/usr/bin/python3"])
    _probe_versions(monkeypatch, {"/usr/bin/python3": "Python 3.9.6"})
    assert PythonLanguage().detect() is None


def test_dev_uses_own_interpreter_even_with_runtime(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(sys, "frozen", False, raising=False)
    monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path), raising=False)
    _fake_runtime(tmp_path)  # a fetched runtime/ must not change what dev runs
    rt = PythonLanguage().detect()
    assert rt is not None and rt.executable == sys.executable


def test_path_candidates_lists_every_match(monkeypatch, tmp_path: Path) -> None:
    if sys.platform == "win32":
        pytest.skip("POSIX executable bits")
    a, b = tmp_path / "a", tmp_path / "b"
    for d in (a, b):
        d.mkdir()
        exe = d / "python3"
        exe.write_text("")
        exe.chmod(0o755)
    monkeypatch.setenv("PATH", f"{a}:{b}")
    found = pylang._path_candidates()
    assert found[:2] == [str(a / "python3"), str(b / "python3")]


def test_doctor_flag_is_hidden_and_reports(capsys) -> None:
    assert "--doctor" not in app.build_parser().format_help()
    app.main(["--doctor"])
    out = capsys.readouterr().out
    assert "content dir:" in out and "languages:" in out and "python:" in out


def _load_build_module():
    spec = importlib.util.spec_from_file_location("coderogue_build", REPO / "tools" / "build.py")
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_build_spec_renders_valid_python(monkeypatch, tmp_path: Path) -> None:
    build = _load_build_module()
    monkeypatch.setattr(build, "BUILD", tmp_path)
    spec = build.render_spec()
    assert spec.parent == tmp_path and spec.name == "CodeRogue.spec"
    text = spec.read_text()
    compile(text, str(spec), "exec")  # the template substituted cleanly
    for _src, dest in build.DATA:
        assert repr(dest) in text
    assert {dest for _src, dest in build.DATA} >= {"content", "assets/fonts", "assets/kenney"}
