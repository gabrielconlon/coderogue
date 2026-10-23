#!/usr/bin/env python3
"""Download a standalone CPython for the player's Python puzzles into runtime/python/.

A frozen CodeRogue cannot run player code with ``sys.executable`` (that is the game), so a
release ships a relocatable CPython from astral-sh/python-build-standalone. This picks the
newest CPython 3.13 ``install_only`` tarball for this platform from the latest release,
checks its SHA-256 against the release, unpacks it and runs ``python -c "print(1)"``.

Usage: python tools/fetch_runtime.py [--force] [--full] [--target TRIPLE] [--release TAG]
                                     [--allow-unverified]

With no published checksum for the asset the download is refused unless --allow-unverified.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import urllib.request
from pathlib import Path

REPO = "astral-sh/python-build-standalone"
API = f"https://api.github.com/repos/{REPO}/releases"
MINOR = "3.13"
ROOT = Path(__file__).resolve().parent.parent
DEST = ROOT / "runtime" / "python"
UA = {"User-Agent": "coderogue-fetch-runtime/0.1", "Accept": "application/vnd.github+json"}


def host_triple() -> str:
    """python-build-standalone target triple for this machine."""
    machine = platform.machine().lower()
    arch = {"arm64": "aarch64", "aarch64": "aarch64", "x86_64": "x86_64", "amd64": "x86_64"}.get(
        machine
    )
    if arch is None:
        raise SystemExit(f"unsupported CPU architecture: {machine}")
    if sys.platform == "darwin":
        return f"{arch}-apple-darwin"
    if sys.platform == "win32":
        return f"{arch}-pc-windows-msvc"
    if sys.platform.startswith("linux"):
        return f"{arch}-unknown-linux-gnu"
    raise SystemExit(f"unsupported platform: {sys.platform}")


def _get_json(url: str) -> object:
    headers = dict(UA)
    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    if token:  # avoids the 60 requests/hour anonymous limit on CI
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.load(r)


def pick_asset(release: dict, triple: str) -> dict:
    """Newest ``cpython-3.13.N+DATE-<triple>-install_only.tar.gz`` asset in ``release``."""
    pat = re.compile(
        rf"^cpython-{re.escape(MINOR)}\.(\d+)\+\d+-{re.escape(triple)}-install_only\.tar\.gz$"
    )
    best: tuple[int, dict] | None = None
    for asset in release.get("assets", []):
        m = pat.match(asset["name"])
        if m and (best is None or int(m.group(1)) > best[0]):
            best = (int(m.group(1)), asset)
    if best is None:
        tag = release["tag_name"]
        raise SystemExit(f"no CPython {MINOR} install_only build for {triple} in {tag}")
    return best[1]


def expected_sha256(release: dict, asset: dict) -> str | None:
    """The asset's SHA-256 from the GitHub digest field, else from the SHA256SUMS file."""
    digest = asset.get("digest") or ""
    if digest.startswith("sha256:"):
        return digest.split(":", 1)[1]
    for a in release.get("assets", []):
        if a["name"] == "SHA256SUMS":
            with urllib.request.urlopen(a["browser_download_url"], timeout=60) as r:
                for line in r.read().decode().splitlines():
                    parts = line.split()
                    if len(parts) == 2 and parts[1] == asset["name"]:
                        return parts[0]
    return None


def download(url: str, dest: Path) -> str:
    """Stream ``url`` to ``dest``; return its SHA-256."""
    h = hashlib.sha256()
    req = urllib.request.Request(url, headers={"User-Agent": UA["User-Agent"]})
    with urllib.request.urlopen(req, timeout=300) as r, dest.open("wb") as f:
        total = int(r.headers.get("Content-Length") or 0)
        done = 0
        while chunk := r.read(1 << 20):
            f.write(chunk)
            h.update(chunk)
            done += len(chunk)
            if total:
                print(f"\r  {done >> 20} / {total >> 20} MB", end="", flush=True)
    print()
    return h.hexdigest()


#: Parts of the stdlib a puzzle never needs (tests, GUI toolkits, headers, pip); pruned to
#: keep the release small. Globs relative to the install root (POSIX and Windows layouts).
PRUNE = (
    "include", "share", "tcl", "Lib/test", "Lib/idlelib", "Lib/tkinter", "Lib/turtledemo",
    "Lib/ensurepip", "Lib/site-packages/pip*", "DLLs/_tkinter.pyd", "DLLs/tcl*.dll",
    "DLLs/tk*.dll", "lib/tcl*", "lib/tk*", "lib/itcl*", "lib/thread*", "lib/libtcl*",
    "lib/libtk*", "lib/python3.*/test", "lib/python3.*/idlelib", "lib/python3.*/tkinter",
    "lib/python3.*/turtledemo", "lib/python3.*/ensurepip", "lib/python3.*/site-packages/pip*",
    "lib/python3.*/lib-dynload/_tkinter*", "lib/python3.*/config-3.*",
)


def prune(base: Path) -> int:
    """Delete :data:`PRUNE` entries under ``base`` and every ``__pycache__``; return bytes freed."""
    freed = 0
    victims = [p for pattern in PRUNE for p in base.glob(pattern)]
    victims += list(base.rglob("__pycache__"))
    for p in victims:
        if not p.exists() and not p.is_symlink():
            continue
        if p.is_dir() and not p.is_symlink():
            files = (f for f in p.rglob("*") if f.is_file() and not f.is_symlink())
            freed += sum(f.stat().st_size for f in files)
            shutil.rmtree(p)
        else:
            freed += p.lstat().st_size
            p.unlink()
    return freed


def runtime_exe(base: Path) -> Path | None:
    for rel in ("python.exe", "bin/python3"):
        if (base / rel).is_file():
            return base / rel
    return None


def verify(base: Path) -> str:
    exe = runtime_exe(base)
    if exe is None:
        raise SystemExit(f"no interpreter found under {base}")
    out = subprocess.run(
        [str(exe), "-I", "-B", "-c", "import sys; print(1, sys.version.split()[0])"],
        capture_output=True, text=True, timeout=60,
    )
    if out.returncode != 0 or not out.stdout.startswith("1 "):
        raise SystemExit(f"runtime check failed: {out.stdout!r} {out.stderr!r}")
    return out.stdout.split()[1]


def check_checksum(name: str, got: str, want: str | None, allow_unverified: bool) -> None:
    """Fail closed: a mismatch always aborts, and so does a missing checksum unless allowed."""
    if want is None:
        if not allow_unverified:
            raise SystemExit(f"release lists no checksum for {name}; refusing to install it "
                             "unverified (pass --allow-unverified to override)")
        print("  warning: release lists no checksum for this asset; not verified")
    elif got != want:
        raise SystemExit(f"checksum mismatch for {name}: {got} != {want}")
    else:
        print(f"  sha256 ok {got[:16]}...")


def install_dir(src: Path, dest: Path) -> None:
    """Move ``src`` to ``dest``, replacing it; the old ``dest`` is removed only after the new
    one is in place (it is put back if the move fails)."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    old = None
    if dest.exists():
        old = dest.with_name(f".{dest.name}.old")
        if old.exists():
            shutil.rmtree(old)
        dest.rename(old)
    try:
        shutil.move(str(src), dest)
    except BaseException:
        if old is not None:
            if dest.exists():
                shutil.rmtree(dest, ignore_errors=True)
            old.rename(dest)
        raise
    if old is not None:
        shutil.rmtree(old, ignore_errors=True)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--force", action="store_true", help="replace an existing runtime/python")
    ap.add_argument("--target", default=None, help="target triple (default: this machine)")
    ap.add_argument("--release", default="latest", help="release tag (default: latest)")
    ap.add_argument("--full", action="store_true", help="keep the whole install (no pruning)")
    ap.add_argument("--allow-unverified", action="store_true",
                    help="install even when the release publishes no checksum for the asset")
    args = ap.parse_args(argv)

    if DEST.exists() and not args.force:
        if runtime_exe(DEST):
            print(f"runtime present: {DEST} (Python {verify(DEST)}); use --force to replace")
            return 0
    triple = args.target or host_triple()
    url = f"{API}/latest" if args.release == "latest" else f"{API}/tags/{args.release}"
    release = _get_json(url)
    assert isinstance(release, dict)
    asset = pick_asset(release, triple)
    print(f"{release['tag_name']}: {asset['name']} ({asset['size'] >> 20} MB)")
    want = expected_sha256(release, asset)

    with tempfile.TemporaryDirectory(prefix="coderogue-runtime-") as tmp:
        tarball = Path(tmp) / asset["name"]
        got = download(asset["browser_download_url"], tarball)
        check_checksum(asset["name"], got, want, args.allow_unverified)
        unpack = Path(tmp) / "unpack"
        with tarfile.open(tarball) as tf:
            tf.extractall(unpack, filter="data")
        src = unpack / "python"
        if not src.is_dir():
            raise SystemExit("unexpected tarball layout (no top-level python/)")
        if not args.full:
            print(f"  pruned {prune(src) >> 20} MB (tests, tkinter, headers, pip)")
        if triple == host_triple():
            verify(src)
        install_dir(src, DEST)

    if triple == host_triple():
        print(f"runtime ready: {DEST} (Python {verify(DEST)})")
    else:
        print(f"runtime unpacked for {triple}: {DEST} (not runnable on this host)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
