#!/usr/bin/env python3
"""Download the Kenney (CC0) asset packs CodeRogue uses into assets/kenney/.

Kenney's zip URLs contain a rotating hash, so each pack page is scraped for
its current download link. Packs already present are skipped unless --force.
Usage: python tools/fetch_assets.py [--force] [pack-slug ...]
"""
from __future__ import annotations

import argparse
import io
import re
import shutil
import sys
import tempfile
import urllib.request
import zipfile
from pathlib import Path

PACKS = [
    "tiny-dungeon",
    "tiny-town",
    "roguelike-rpg-pack",
    "pixel-ui-pack",
    "kenney-fonts",
    "rpg-audio",
    "interface-sounds",
    "music-jingles",
]
PAGE = "https://kenney.nl/assets/{slug}"
ZIP_RE = re.compile(r"""https://kenney\.nl/media/pages/assets/[^\s"'<>]+?\.zip""")
ROOT = Path(__file__).resolve().parent.parent / "assets" / "kenney"
UA = {"User-Agent": "Mozilla/5.0 (compatible; coderogue-fetch-assets/0.1)"}


def find_zip_url(slug: str) -> str:
    req = urllib.request.Request(PAGE.format(slug=slug), headers=UA)
    with urllib.request.urlopen(req, timeout=30) as r:
        html = r.read().decode("utf-8", "replace")
    m = ZIP_RE.search(html)
    if not m:
        raise RuntimeError(f"no zip link found on {PAGE.format(slug=slug)}")
    return m.group(0)


def fetch(slug: str, force: bool) -> Path:
    dest = ROOT / slug
    if dest.exists() and any(dest.iterdir()) and not force:
        print(f"  {slug}: present, skipping")
        return dest
    url = find_zip_url(slug)
    print(f"  {slug}: downloading {url}")
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=120) as r:
        data = r.read()
    install_zip(data, dest)
    print(f"  {slug}: {sum(1 for _ in dest.rglob('*') if _.is_file())} files")
    return dest


def install_zip(data: bytes, dest: Path) -> None:
    """Unpack zip ``data`` into ``dest`` atomically.

    Every member must land inside ``dest`` (no ``..`` or absolute paths). The archive is
    extracted into a temp dir next to ``dest`` and renamed into place only once complete, so
    an interrupted run never leaves a half pack that later looks "present".
    """
    dest.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=f".{dest.name}.", dir=dest.parent))
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            root = staging.resolve()
            for info in zf.infolist():
                # Refuse path traversal in untrusted archives.
                target = (root / info.filename).resolve()
                if not target.is_relative_to(root):
                    raise RuntimeError(f"unsafe path in zip: {info.filename}")
            zf.extractall(staging)
        old = None
        if dest.exists():
            old = dest.with_name(f".{dest.name}.old")
            if old.exists():
                shutil.rmtree(old)
            dest.rename(old)
        staging.rename(dest)
        if old is not None:
            shutil.rmtree(old, ignore_errors=True)
    finally:
        if staging.exists():
            shutil.rmtree(staging, ignore_errors=True)


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("packs", nargs="*", default=PACKS)
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args(argv)
    ROOT.mkdir(parents=True, exist_ok=True)
    print(f"Fetching Kenney packs into {ROOT}")
    failures = 0
    for slug in args.packs:
        try:
            fetch(slug, args.force)
        except Exception as e:  # noqa: BLE001
            failures += 1
            print(f"  {slug}: FAILED: {e}", file=sys.stderr)
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
