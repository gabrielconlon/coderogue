#!/usr/bin/env python3
"""Build a self-contained CodeRogue with PyInstaller (one folder, no Python needed).

    python tools/build.py [--clean] [--no-runtime]

Output: ``dist/CodeRogue.app`` on macOS, ``dist/CodeRogue/CodeRogue.exe`` on Windows,
``dist/CodeRogue/CodeRogue`` on Linux. The spec is rendered from ``tools/coderogue.spec.in``
into ``build/`` (never the repo root). Bundled: ``content/``, ``assets/fonts/``,
``assets/kenney/`` and, when ``tools/fetch_runtime.py`` has been run, ``runtime/python/``.
See docs/PACKAGING.md.
"""
from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import tomllib
from pathlib import Path
from string import Template

ROOT = Path(__file__).resolve().parent.parent
TOOLS = ROOT / "tools"
BUILD = ROOT / "build"
DIST = ROOT / "dist"
NAME = "CodeRogue"
BUNDLE_ID = "io.github.coderogue"

#: (source relative to repo, destination inside the bundle). The destination is relative to
#: ``sys._MEIPASS``, which is what ``coderogue.app.resource_path`` joins onto.
DATA = (
    ("content", "content"),
    ("assets/fonts", "assets/fonts"),
    ("assets/kenney", "assets/kenney"),
)
#: pygame-ce ships its own PyInstaller hook; yaml's C loader is optional, so name it.
HIDDEN_IMPORTS = ["yaml", "pygame.freetype"]
EXCLUDES = ["tkinter", "pytest", "_pytest", "ruff", "setuptools", "pip"]
ICONS = {"darwin": "assets/icon/coderogue.icns", "win32": "assets/icon/coderogue.ico"}


def fail(msg: str) -> None:
    print(f"build: {msg}", file=sys.stderr)
    raise SystemExit(1)


def version() -> str:
    with (ROOT / "pyproject.toml").open("rb") as f:
        return tomllib.load(f)["project"]["version"]


def check_inputs() -> None:
    kenney = ROOT / "assets" / "kenney"
    if not kenney.is_dir() or not any(kenney.iterdir()):
        fail("assets/kenney/ is missing. Run `python tools/fetch_assets.py` first.")
    for src, _ in DATA:
        if not (ROOT / src).is_dir():
            fail(f"{src}/ is missing")
    try:
        import PyInstaller  # noqa: F401
    except ImportError:
        fail('PyInstaller is not installed. Run `pip install -e ".[build]"`.')


def icon_path() -> str | None:
    rel = ICONS.get(sys.platform)
    if rel and (ROOT / rel).is_file():
        return str(ROOT / rel)
    return None


def render_spec() -> Path:
    """Write build/CodeRogue.spec from the template; every value is a Python literal."""
    BUILD.mkdir(exist_ok=True)
    entry = BUILD / "coderogue_entry.py"
    entry.write_text("from coderogue.app import main\n\nraise SystemExit(main())\n")
    windowed = sys.platform in ("darwin", "win32")
    values = {
        "entry": repr(str(entry)),
        "repo": repr(str(ROOT)),
        "datas": repr([(str(ROOT / src), dest) for src, dest in DATA]),
        "hiddenimports": repr(HIDDEN_IMPORTS),
        "excludes": repr(EXCLUDES),
        "app_name": repr(NAME),
        "console": repr(not windowed),
        "icon": repr(icon_path()),
        "macos_bundle": repr(sys.platform == "darwin"),
        "bundle_id": repr(BUNDLE_ID),
        "version": repr(version()),
    }
    spec = BUILD / f"{NAME}.spec"
    template = Template((TOOLS / "coderogue.spec.in").read_text())
    spec.write_text(template.substitute(values))
    return spec


def run_pyinstaller(spec: Path, clean: bool) -> None:
    cmd = [
        sys.executable, "-m", "PyInstaller", str(spec), "--noconfirm",
        "--distpath", str(DIST), "--workpath", str(BUILD / "pyinstaller"),
    ]
    if clean:
        cmd.append("--clean")
    print("build: " + " ".join(cmd))
    subprocess.run(cmd, check=True, cwd=ROOT)


def output_path() -> Path:
    return DIST / f"{NAME}.app" if sys.platform == "darwin" else DIST / NAME


def meipass_dir(out: Path) -> Path:
    """The folder PyInstaller sets as ``sys._MEIPASS`` in a onedir build."""
    if sys.platform == "darwin":
        return out / "Contents" / "Frameworks"
    return out / "_internal"


def add_runtime(out: Path) -> bool:
    """Copy runtime/python/ into the bundle so resource_path('runtime', 'python') finds it.

    Copied after PyInstaller (not via ``datas``) so the interpreter keeps its own layout
    and symlinks. In a .app the tree goes to Contents/Resources (where non-code belongs)
    with a Contents/Frameworks/runtime symlink, the same split PyInstaller uses for data.
    """
    src = ROOT / "runtime" / "python"
    if not src.is_dir():
        return False
    if sys.platform == "darwin":
        dest = out / "Contents" / "Resources" / "runtime" / "python"
        link = meipass_dir(out) / "runtime"
    else:
        dest = meipass_dir(out) / "runtime" / "python"
        link = None
    if dest.exists():
        shutil.rmtree(dest)
    shutil.copytree(src, dest, symlinks=True,
                    ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    if link is not None:
        if link.is_symlink() or link.exists():
            link.unlink()
        link.symlink_to(Path("..") / "Resources" / "runtime")
    return True


def adhoc_sign(out: Path) -> None:
    """Re-seal the .app after adding files (ad-hoc; real signing is a TODO in PACKAGING.md)."""
    if sys.platform != "darwin" or not shutil.which("codesign"):
        return
    cp = subprocess.run(["codesign", "--force", "--deep", "--sign", "-", str(out)],
                        capture_output=True, text=True)
    if cp.returncode != 0:
        print(f"build: warning: ad-hoc codesign failed: {cp.stderr.strip()}")


def tree_size(path: Path) -> int:
    total = 0
    for dirpath, _dirs, files in os.walk(path):
        for f in files:
            p = Path(dirpath) / f
            if not p.is_symlink():
                total += p.stat().st_size
    return total


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Build CodeRogue with PyInstaller")
    ap.add_argument("--clean", action="store_true", help="clear PyInstaller's cache first")
    ap.add_argument("--no-runtime", action="store_true",
                    help="do not bundle runtime/python even if present")
    args = ap.parse_args(argv)

    check_inputs()
    spec = render_spec()
    print(f"build: spec written to {spec}")
    run_pyinstaller(spec, args.clean)
    out = output_path()
    if not out.exists():
        fail(f"PyInstaller finished but {out} is missing")
    bundled = False if args.no_runtime else add_runtime(out)
    adhoc_sign(out)
    if not bundled:
        print("build: no runtime/python bundled; Python puzzles will need python3 on PATH "
              "(run tools/fetch_runtime.py to bundle one)")
    size = tree_size(out)
    print(f"build: {out}")
    print(f"build: size {size / (1 << 20):.1f} MB (runtime bundled: {bundled})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
