"""Tiled ``.tmj`` (JSON) map loader. Pure Python: no pygame import.

Supported subset (see ``content/maps/README.md``):

* orthogonal maps, any square tile size (16 px in practice)
* tile layers with CSV/array ``data`` (no base64/compression), optionally inside groups
* tilesets embedded in the map or referenced by ``source`` (a ``.tsj`` JSON tileset);
  ``image`` paths are resolved relative to the file that declares them
* water: every non-empty cell of a tile layer named ``water`` (or of any tile layer with
  a truthy ``water`` custom property) is listed in :attr:`MapData.water`; the renderer tints
  those cells and the collision grid treats them as solid
* object layers; objects keep ``type`` (or Tiled 1.9's ``class``), ``name`` and custom
  ``properties`` flattened into a dict
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# Tiled stores flip/rotation flags in the top bits of each gid.
FLIP_H = 0x80000000
FLIP_V = 0x40000000
FLIP_D = 0x20000000
ROTATE_HEX = 0x10000000
GID_MASK = ~(FLIP_H | FLIP_V | FLIP_D | ROTATE_HEX) & 0xFFFFFFFF

KNOWN_OBJECT_TYPES = frozenset({"player_spawn", "altar", "enemy", "npc", "door", "chest"})


class MapFormatError(ValueError):
    """Raised when a map uses a Tiled feature we do not support."""


@dataclass(frozen=True)
class TilesetInfo:
    """A tileset as declared by the map (image path already resolved)."""

    firstgid: int
    name: str
    image: Path
    columns: int
    tilecount: int
    tilewidth: int
    tileheight: int
    spacing: int = 0
    margin: int = 0

    def source_rect(self, local_id: int) -> tuple[int, int, int, int]:
        """Pixel rect (x, y, w, h) of ``local_id`` inside the tileset image."""
        col = local_id % self.columns
        row = local_id // self.columns
        x = self.margin + col * (self.tilewidth + self.spacing)
        y = self.margin + row * (self.tileheight + self.spacing)
        return (x, y, self.tilewidth, self.tileheight)


@dataclass
class TileLayer:
    """A tile layer: ``data`` is row-major gids (0 = empty), flip flags stripped."""

    name: str
    width: int
    height: int
    data: list[int]
    visible: bool = True
    properties: dict[str, Any] = field(default_factory=dict)

    def gid_at(self, tx: int, ty: int) -> int:
        """Gid at tile coords (0 if out of bounds)."""
        if 0 <= tx < self.width and 0 <= ty < self.height:
            return self.data[ty * self.width + tx]
        return 0


@dataclass
class MapObject:
    """An object from an object layer. ``x``/``y`` is the top-left corner in pixels."""

    id: int
    name: str
    type: str
    x: float
    y: float
    width: float
    height: float
    properties: dict[str, Any] = field(default_factory=dict)
    gid: int = 0

    @property
    def center(self) -> tuple[float, float]:
        """Centre point in pixels."""
        return (self.x + self.width / 2, self.y + self.height / 2)


@dataclass
class MapData:
    """Everything parsed out of a ``.tmj`` file."""

    path: Path
    width: int
    height: int
    tilewidth: int
    tileheight: int
    tilesets: list[TilesetInfo]
    layers: dict[str, TileLayer]
    layer_order: list[str]
    objects: list[MapObject]
    properties: dict[str, Any] = field(default_factory=dict)
    water: set[tuple[int, int]] = field(default_factory=set)
    """Tile coords ``(tx, ty)`` of water cells (see :func:`water_cells`)."""

    @property
    def pixel_size(self) -> tuple[int, int]:
        """Map size in pixels."""
        return (self.width * self.tilewidth, self.height * self.tileheight)

    def tileset_for(self, gid: int) -> TilesetInfo | None:
        """The tileset that owns ``gid`` (highest firstgid <= gid)."""
        if gid <= 0:
            return None
        found: TilesetInfo | None = None
        for ts in self.tilesets:
            if ts.firstgid <= gid:
                found = ts
            else:
                break
        return found

    def objects_of_type(self, type_: str) -> list[MapObject]:
        """All objects whose ``type`` equals ``type_``."""
        return [o for o in self.objects if o.type == type_]

    def first_object(self, type_: str) -> MapObject | None:
        """First object of ``type_`` or None."""
        for o in self.objects:
            if o.type == type_:
                return o
        return None


WATER_LAYER = "water"


def is_water_layer(layer: TileLayer) -> bool:
    """True for a layer named ``water`` or one carrying a truthy ``water`` property."""
    return layer.name == WATER_LAYER or bool(layer.properties.get(WATER_LAYER))


def water_cells(layers: dict[str, TileLayer]) -> set[tuple[int, int]]:
    """Tile coords of every non-empty cell on a water layer."""
    cells: set[tuple[int, int]] = set()
    for layer in layers.values():
        if not is_water_layer(layer):
            continue
        for i, gid in enumerate(layer.data):
            if gid:
                cells.add((i % layer.width, i // layer.width))
    return cells


def _properties(raw: list[dict[str, Any]] | None) -> dict[str, Any]:
    return {p["name"]: p.get("value") for p in (raw or [])}


def _load_tileset(entry: dict[str, Any], base_dir: Path) -> TilesetInfo:
    firstgid = int(entry["firstgid"])
    if "source" in entry:
        src = (base_dir / entry["source"]).resolve()
        if src.suffix.lower() not in (".tsj", ".json"):
            raise MapFormatError(f"external tileset must be JSON (.tsj): {src}")
        with src.open(encoding="utf-8") as fh:
            ts = json.load(fh)
        ts_dir = src.parent
    else:
        ts = entry
        ts_dir = base_dir
    if "image" not in ts:
        raise MapFormatError("image-collection tilesets are not supported")
    tilewidth = int(ts["tilewidth"])
    tileheight = int(ts["tileheight"])
    spacing = int(ts.get("spacing", 0))
    margin = int(ts.get("margin", 0))
    columns = int(ts.get("columns") or 0)
    if columns <= 0:
        columns = max(1, (int(ts["imagewidth"]) - 2 * margin + spacing) // (tilewidth + spacing))
    tilecount = int(ts.get("tilecount") or 0)
    return TilesetInfo(
        firstgid=firstgid,
        name=str(ts.get("name", "")),
        image=(ts_dir / ts["image"]).resolve(),
        columns=columns,
        tilecount=tilecount,
        tilewidth=tilewidth,
        tileheight=tileheight,
        spacing=spacing,
        margin=margin,
    )


def _parse_layer_data(layer: dict[str, Any]) -> list[int]:
    if layer.get("encoding", "csv") != "csv" or "compression" in layer:
        raise MapFormatError(
            f"layer {layer.get('name')!r}: only CSV layer format is supported "
            "(Tiled: Map > Map Properties > Tile Layer Format = CSV)"
        )
    data = layer.get("data")
    if data is None:
        raise MapFormatError(f"layer {layer.get('name')!r}: infinite/chunked maps unsupported")
    if isinstance(data, str):  # tolerate a raw CSV string
        data = [int(v) for v in data.replace("\n", "").split(",") if v.strip()]
    return [int(g) & GID_MASK for g in data]


def _parse_object(obj: dict[str, Any]) -> MapObject:
    width = float(obj.get("width", 0))
    height = float(obj.get("height", 0))
    y = float(obj.get("y", 0))
    gid = int(obj.get("gid", 0)) & GID_MASK
    if gid:
        y -= height  # tile objects are anchored bottom-left in Tiled
    return MapObject(
        id=int(obj.get("id", 0)),
        name=str(obj.get("name", "")),
        type=str(obj.get("type") or obj.get("class") or ""),
        x=float(obj.get("x", 0)),
        y=y,
        width=width,
        height=height,
        properties=_properties(obj.get("properties")),
        gid=gid,
    )


def _walk_layers(layers: list[dict[str, Any]]):
    for layer in layers:
        if layer.get("type") == "group":
            yield from _walk_layers(layer.get("layers", []))
        else:
            yield layer


def parse_map(raw: dict[str, Any], path: Path) -> MapData:
    """Build :class:`MapData` from already-decoded Tiled JSON. ``path`` anchors relative paths."""
    if raw.get("orientation", "orthogonal") != "orthogonal":
        raise MapFormatError("only orthogonal maps are supported")
    if raw.get("infinite"):
        raise MapFormatError("infinite maps are not supported; uncheck 'Infinite' in Tiled")
    base_dir = path.parent
    tilesets = sorted(
        (_load_tileset(ts, base_dir) for ts in raw.get("tilesets", [])), key=lambda t: t.firstgid
    )
    layers: dict[str, TileLayer] = {}
    order: list[str] = []
    objects: list[MapObject] = []
    width = int(raw["width"])
    height = int(raw["height"])
    for layer in _walk_layers(raw.get("layers", [])):
        kind = layer.get("type")
        if kind == "tilelayer":
            data = _parse_layer_data(layer)
            lw = int(layer.get("width", width))
            lh = int(layer.get("height", height))
            if len(data) != lw * lh:
                raise MapFormatError(
                    f"layer {layer.get('name')!r}: expected {lw * lh} tiles, got {len(data)}"
                )
            name = str(layer.get("name", f"layer{len(order)}"))
            layers[name] = TileLayer(
                name=name,
                width=lw,
                height=lh,
                data=data,
                visible=bool(layer.get("visible", True)),
                properties=_properties(layer.get("properties")),
            )
            order.append(name)
        elif kind == "objectgroup":
            objects.extend(_parse_object(o) for o in layer.get("objects", []))
    return MapData(
        path=path,
        width=width,
        height=height,
        tilewidth=int(raw["tilewidth"]),
        tileheight=int(raw["tileheight"]),
        tilesets=tilesets,
        layers=layers,
        layer_order=order,
        objects=objects,
        properties=_properties(raw.get("properties")),
        water=water_cells(layers),
    )


def load_map(path: str | Path) -> MapData:
    """Read and parse a ``.tmj`` file."""
    p = Path(path).resolve()
    with p.open(encoding="utf-8") as fh:
        raw = json.load(fh)
    return parse_map(raw, p)
