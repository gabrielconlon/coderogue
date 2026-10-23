"""Generate Tiled ``.tmj`` maps from readable ASCII sources in ``content/maps/src``.

Usage::

    python tools/mapgen.py                 # regenerate every content/maps/src/*.map
    python tools/mapgen.py src/foo.map     # regenerate just these
    python tools/mapgen.py --check         # regenerate to a temp dir, diff against committed

Source format (see ``content/maps/README.md``, "Authoring with mapgen")::

    name: little_tilde              # output stem -> content/maps/little_tilde.tmj
    area: Little Tilde              # map property shown in the HUD
    chapter: 0                      # map property (int)
    tilesets: town dungeon          # first one is the default sheet for bare ids
    seed: 7                         # optional; default is crc32(name)
    legend:
      . ground=town:0,0,0,1,2       # comma list = seeded random pick per cell;
                                    # bare ids reuse the previous sheet
      T ground=town:0 wall=town:16  # wall = walls layer (solid)
      D ground=town:25 decor=town:85 above=...
      ~ ground=dungeon:0 wall=dungeon:0,12 water=1   # water=1 marks water (tinted, solid);
                                    # water=sheet:id draws a tile on a `water` layer too
    grid:
    TTTT.....
    objects:
    player_spawn spawn 10 5
    altar lantern @A puzzle=ch0-01   # @A = the unique cell holding legend char A
    door to_vale 20 0 target=echo_vale spawn=from_tilde requires_solved=ch0-03

Object values are typed: ints, floats, ``true``/``false`` become int/float/bool; everything
else is a string. Use shell quoting for spaces (``name="Old Hob"``).
"""

from __future__ import annotations

import argparse
import difflib
import json
import random
import re
import shlex
import sys
import tempfile
import zlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
MAPS_DIR = REPO_ROOT / "content" / "maps"
SRC_DIR = MAPS_DIR / "src"

TILE_SIZE = 16
LAYERS = ("ground", "walls", "water", "decor", "above")
LEGEND_KEYS = {"ground": "ground", "wall": "walls", "walls": "walls", "water": "water",
               "decor": "decor", "above": "above"}
WATER_FLAGS = ("1", "true")  # ``water=1``: mark the cell as water without a tile of its own


@dataclass(frozen=True)
class Sheet:
    """A known Kenney sheet (packed, 16 px, 12 columns, no spacing)."""

    name: str
    image: str  # relative to content/maps/
    columns: int = 12
    tilecount: int = 132
    imagewidth: int = 192
    imageheight: int = 176


SHEETS: dict[str, Sheet] = {
    "town": Sheet("tiny-town", "../../assets/kenney/tiny-town/Tilemap/tilemap_packed.png"),
    "dungeon": Sheet("tiny-dungeon", "../../assets/kenney/tiny-dungeon/Tilemap/tilemap_packed.png"),
}


class MapSourceError(ValueError):
    """A ``.map`` source is malformed."""


@dataclass
class MapSource:
    """A parsed ``.map`` file."""

    path: Path
    header: dict[str, str] = field(default_factory=dict)
    tilesets: list[str] = field(default_factory=list)
    legend: dict[str, dict[str, list[tuple[str, int]]]] = field(default_factory=dict)
    grid: list[str] = field(default_factory=list)
    objects: list[tuple[int, list[str]]] = field(default_factory=list)  # (line no, tokens)

    @property
    def name(self) -> str:
        return self.header.get("name") or self.path.stem


def _err(path: Path, lineno: int, msg: str) -> MapSourceError:
    return MapSourceError(f"{path}:{lineno}: {msg}")


def _parse_tile_ref(
    ref: str, tilesets: list[str], path: Path, lineno: int, default: str | None = None
) -> tuple[str, int]:
    """``sheet:id`` or a bare ``id`` (in ``default``, else the first declared tileset)."""
    sheet, _, tid = ref.rpartition(":")
    sheet = sheet or default or tilesets[0]
    if sheet not in tilesets:
        raise _err(path, lineno, f"tileset {sheet!r} not declared in 'tilesets:'")
    try:
        value = int(tid)
    except ValueError:
        raise _err(path, lineno, f"bad tile id {ref!r}") from None
    if not 0 <= value < SHEETS[sheet].tilecount:
        raise _err(path, lineno, f"tile id {value} out of range for {sheet}")
    return (sheet, value)


def parse_source(text: str, path: Path) -> MapSource:
    """Parse ``.map`` source text."""
    src = MapSource(path=path)
    section = "header"
    for lineno, raw in enumerate(text.splitlines(), start=1):
        if section == "grid":
            if raw.strip() == "objects:":
                section = "objects"
            elif raw.strip():
                src.grid.append(raw.rstrip())
            continue
        line = raw.split("#", 1)[0].rstrip() if section != "legend" else raw.rstrip()
        if not line.strip():
            continue
        stripped = line.strip()
        if stripped in ("legend:", "grid:", "objects:"):
            section = stripped[:-1]
            if section == "legend" and not src.tilesets:
                raise _err(path, lineno, "'tilesets:' must come before 'legend:'")
            continue
        if section == "header":
            key, sep, value = stripped.partition(":")
            if not sep:
                raise _err(path, lineno, f"expected 'key: value', got {stripped!r}")
            key, value = key.strip(), value.strip()
            if key == "tilesets":
                src.tilesets = value.split()
                for ts in src.tilesets:
                    if ts not in SHEETS:
                        raise _err(path, lineno, f"unknown tileset {ts!r} ({', '.join(SHEETS)})")
            src.header[key] = value
        elif section == "legend":
            body = stripped
            if body.startswith("#") and len(body) > 1 and body[1] == "#":
                continue  # '## comment' inside the legend ('#' itself is a valid char)
            char, rest = body[0], body[1:]
            if rest and not rest[0].isspace():
                raise _err(path, lineno, "legend entries are '<char> key=value ...'")
            entry: dict[str, list[tuple[str, int]]] = {}
            for tok in rest.split():
                key, sep, value = tok.partition("=")
                if not sep or key not in LEGEND_KEYS:
                    keys = ", ".join(LEGEND_KEYS)
                    raise _err(path, lineno, f"bad legend token {tok!r} (keys: {keys})")
                refs: list[tuple[str, int]] = []
                if LEGEND_KEYS[key] == "water" and value in WATER_FLAGS:
                    entry["water"] = refs  # empty = marker only
                    continue
                for r in value.split(","):  # a bare id reuses the previous ref's sheet
                    prev = refs[-1][0] if refs else None
                    refs.append(_parse_tile_ref(r, src.tilesets, path, lineno, prev))
                entry[LEGEND_KEYS[key]] = refs
            if char in src.legend:
                raise _err(path, lineno, f"legend char {char!r} defined twice")
            src.legend[char] = entry
        elif section == "objects":
            try:
                tokens = shlex.split(stripped)
            except ValueError as exc:
                raise _err(path, lineno, str(exc)) from None
            src.objects.append((lineno, tokens))
    if not src.tilesets:
        raise MapSourceError(f"{path}: missing 'tilesets:'")
    if not src.grid:
        raise MapSourceError(f"{path}: missing 'grid:'")
    width = len(src.grid[0])
    for i, row in enumerate(src.grid):
        if len(row) != width:
            raise MapSourceError(f"{path}: grid row {i} has width {len(row)}, expected {width}")
        for ch in row:
            if ch not in src.legend:
                raise MapSourceError(f"{path}: grid row {i} uses {ch!r}, not in the legend")
    return src


def _typed(value: str) -> tuple[str, Any]:
    if re.fullmatch(r"-?\d+", value):
        return ("int", int(value))
    if re.fullmatch(r"-?\d+\.\d*", value):
        return ("float", float(value))
    if value in ("true", "false"):
        return ("bool", value == "true")
    return ("string", value)


def _locate(src: MapSource, char: str, lineno: int) -> tuple[int, int]:
    hits = [(x, y) for y, row in enumerate(src.grid) for x, ch in enumerate(row) if ch == char]
    if len(hits) != 1:
        raise _err(src.path, lineno, f"@{char} must appear exactly once in the grid "
                                     f"(found {len(hits)})")
    return hits[0]


def build_objects(src: MapSource) -> list[dict[str, Any]]:
    """Tiled object dicts (rectangles, one tile big) from the ``objects:`` section."""
    out: list[dict[str, Any]] = []
    width, height = len(src.grid[0]), len(src.grid)
    for oid, (lineno, tokens) in enumerate(src.objects, start=1):
        if len(tokens) < 3:
            raise _err(src.path, lineno, "expected 'type name x y key=value ...'")
        otype, name = tokens[0], tokens[1]
        if tokens[2].startswith("@"):
            tx, ty = _locate(src, tokens[2][1:], lineno)
            rest = tokens[3:]
        else:
            try:
                tx, ty = int(tokens[2]), int(tokens[3])
            except (ValueError, IndexError):
                raise _err(src.path, lineno, "position must be 'x y' or '@<char>'") from None
            rest = tokens[4:]
        if not (0 <= tx < width and 0 <= ty < height):
            raise _err(src.path, lineno, f"({tx}, {ty}) is outside the {width}x{height} map")
        obj: dict[str, Any] = {
            "id": oid,
            "name": name,
            "type": otype,
            "x": tx * TILE_SIZE,
            "y": ty * TILE_SIZE,
            "width": TILE_SIZE,
            "height": TILE_SIZE,
            "rotation": 0,
            "visible": True,
        }
        props = []
        for tok in rest:
            key, sep, value = tok.partition("=")
            if not sep or not key:
                raise _err(src.path, lineno, f"bad property {tok!r} (want key=value)")
            ptype, pvalue = _typed(value)
            props.append({"name": key, "type": ptype, "value": pvalue})
        if props:
            obj["properties"] = props
        out.append(obj)
    return out


def build_map(src: MapSource) -> dict[str, Any]:
    """The Tiled JSON dict for ``src``."""
    width, height = len(src.grid[0]), len(src.grid)
    seed_text = src.header.get("seed")
    seed = int(seed_text) if seed_text else zlib.crc32(src.name.encode("utf-8"))
    rng = random.Random(seed)
    firstgids: dict[str, int] = {}
    gid = 1
    tilesets: list[dict[str, Any]] = []
    for ts in src.tilesets:
        sheet = SHEETS[ts]
        firstgids[ts] = gid
        tilesets.append({
            "columns": sheet.columns,
            "firstgid": gid,
            "image": sheet.image,
            "imageheight": sheet.imageheight,
            "imagewidth": sheet.imagewidth,
            "margin": 0,
            "name": sheet.name,
            "spacing": 0,
            "tilecount": sheet.tilecount,
            "tileheight": TILE_SIZE,
            "tilewidth": TILE_SIZE,
        })
        gid += sheet.tilecount
    data: dict[str, list[int]] = {name: [] for name in LAYERS}
    water_drawn = False  # any cell with a real water tile (else the layer is a hidden mask)
    for row in src.grid:
        for ch in row:
            entry = src.legend[ch]
            for layer in LAYERS:
                choices = entry.get(layer)
                if layer == "water" and choices is not None and not choices:
                    # marker: repeat the cell's top tile so the layer is harmless if shown
                    data[layer].append(data["walls"][-1] or data["ground"][-1] or 1)
                    continue
                if not choices:
                    data[layer].append(0)
                    continue
                if layer == "water":
                    water_drawn = True
                sheet, tid = choices[0] if len(choices) == 1 else rng.choice(choices)
                data[layer].append(firstgids[sheet] + tid)
    layers: list[dict[str, Any]] = []
    for layer in LAYERS:
        if layer in ("water", "decor", "above") and not any(data[layer]):
            continue
        tile_layer: dict[str, Any] = {
            "data": data[layer],
            "height": height,
            "id": len(layers) + 1,
            "name": layer,
            "opacity": 1,
            "type": "tilelayer",
            "visible": water_drawn if layer == "water" else True,
            "width": width,
            "x": 0,
            "y": 0,
        }
        if layer == "water":
            tile_layer["properties"] = [{"name": "water", "type": "bool", "value": True}]
        layers.append(tile_layer)
    objects = build_objects(src)
    layers.append({
        "draworder": "topdown",
        "id": len(layers) + 1,
        "name": "objects",
        "objects": objects,
        "opacity": 1,
        "type": "objectgroup",
        "visible": True,
        "x": 0,
        "y": 0,
    })
    properties = [{"name": "name", "type": "string", "value": src.name}]
    for key in sorted(src.header):
        if key in ("name", "tilesets", "seed"):
            continue
        ptype, pvalue = _typed(src.header[key])
        properties.append({"name": key, "type": ptype, "value": pvalue})
    return {
        "compressionlevel": -1,
        "height": height,
        "infinite": False,
        "layers": layers,
        "nextlayerid": len(layers) + 1,
        "nextobjectid": len(objects) + 1,
        "orientation": "orthogonal",
        "properties": properties,
        "renderorder": "right-down",
        "tiledversion": "1.11.0",
        "tileheight": TILE_SIZE,
        "tilesets": tilesets,
        "tilewidth": TILE_SIZE,
        "type": "map",
        "version": "1.10",
        "width": width,
    }


def dump_map(tmj: dict[str, Any]) -> str:
    """Serialize deterministically, one map row per line in each ``data`` array."""
    width = int(tmj["width"])
    rows: dict[str, str] = {}
    shallow = json.loads(json.dumps(tmj))
    for i, layer in enumerate(shallow["layers"]):
        if "data" in layer:
            token = f"__DATA_{i}__"
            values = layer["data"]
            lines = [
                ",".join(str(v) for v in values[r : r + width])
                for r in range(0, len(values), width)
            ]
            rows[token] = "[\n    " + ",\n    ".join(lines) + "\n   ]"
            layer["data"] = token
    text = json.dumps(shallow, indent=1, sort_keys=False)
    for token, body in rows.items():
        text = text.replace(f'"{token}"', body)
    return text + "\n"


def generate(src_path: Path, out_dir: Path) -> Path:
    """Generate ``out_dir/<name>.tmj`` from ``src_path``; returns the output path."""
    src = parse_source(src_path.read_text(encoding="utf-8"), src_path)
    out = out_dir / f"{src.name}.tmj"
    out.write_text(dump_map(build_map(src)), encoding="utf-8", newline="\n")
    return out


def default_sources() -> list[Path]:
    """Every ``content/maps/src/*.map``, sorted."""
    return sorted(SRC_DIR.glob("*.map"))


def check(sources: list[Path], maps_dir: Path = MAPS_DIR) -> list[str]:
    """Regenerate into a temp dir; return a list of problems (empty = up to date)."""
    problems: list[str] = []
    with tempfile.TemporaryDirectory() as tmp:
        for src_path in sources:
            fresh = generate(src_path, Path(tmp))
            committed = maps_dir / fresh.name
            if not committed.exists():
                problems.append(f"{committed} is missing (run tools/mapgen.py)")
                continue
            a = committed.read_text(encoding="utf-8").splitlines(keepends=True)
            b = fresh.read_text(encoding="utf-8").splitlines(keepends=True)
            if a != b:
                diff = "".join(list(difflib.unified_diff(a, b, str(committed), "regenerated"))[:40])
                problems.append(f"{committed} is stale:\n{diff}")
    return problems


def main(argv: list[str] | None = None) -> int:
    """CLI entry point."""
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("sources", nargs="*", type=Path, help=".map files (default: all)")
    parser.add_argument("--check", action="store_true", help="diff against committed .tmj")
    parser.add_argument("--out", type=Path, default=MAPS_DIR, help="output directory")
    args = parser.parse_args(argv)
    sources = [p.resolve() for p in args.sources] or default_sources()
    try:
        if args.check:
            problems = check(sources, args.out)
            for p in problems:
                print(p, file=sys.stderr)
            return 1 if problems else 0
        for src_path in sources:
            print(f"wrote {generate(src_path, args.out)}")
    except MapSourceError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
