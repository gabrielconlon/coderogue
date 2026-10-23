"""Water: the mapgen ``water=`` legend key, the loader's water cells, collision and tint."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

import pygame
import pytest

from coderogue.world.loader import load_map, parse_map
from coderogue.world.tilemap import WATER_FRAME_TIME, TileMap

REPO = Path(__file__).resolve().parent.parent
MAPS = REPO / "content" / "maps"

SOURCE = """\
name: pond
tilesets: town dungeon
legend:
  . ground=town:0
  ~ ground=dungeon:0 wall=dungeon:0,12 water=1
  = ground=dungeon:37
grid:
.....
.~=~.
.....
objects:
player_spawn spawn 0 0
"""


def _load_mapgen() -> ModuleType:
    spec = importlib.util.spec_from_file_location("mapgen", REPO / "tools" / "mapgen.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["mapgen"] = module
    spec.loader.exec_module(module)
    return module


mapgen = _load_mapgen()


@pytest.fixture(autouse=True)
def _pygame() -> None:
    pygame.init()


def _generate(tmp_path: Path, text: str = SOURCE) -> Path:
    """Generate into ``tmp/maps/out`` so the sheets' ``../../assets`` paths resolve."""
    assets = tmp_path / "assets"
    if not assets.exists():
        assets.symlink_to(REPO / "assets", target_is_directory=True)
    out = tmp_path / "maps" / "out"
    out.mkdir(parents=True, exist_ok=True)
    src = tmp_path / "pond.map"
    src.write_text(text)
    return mapgen.generate(src, out)


def test_mapgen_emits_hidden_water_mask(tmp_path: Path) -> None:
    data = load_map(_generate(tmp_path))
    assert data.layer_order == ["ground", "walls", "water"]
    layer = data.layers["water"]
    assert layer.visible is False and layer.properties == {"water": True}
    assert data.water == {(1, 1), (3, 1)}
    # the mask repeats the cell's own wall tile, so showing it changes nothing
    assert layer.gid_at(1, 1) == data.layers["walls"].gid_at(1, 1)


def test_mapgen_water_tile_ref_makes_a_visible_layer(tmp_path: Path) -> None:
    text = SOURCE.replace("water=1", "water=dungeon:12")
    data = load_map(_generate(tmp_path, text))
    assert data.layers["water"].visible is True
    assert data.layers["water"].gid_at(1, 1) == 133 + 12
    assert data.water == {(1, 1), (3, 1)}


def test_maps_without_water_have_no_water_layer(tmp_path: Path) -> None:
    text = SOURCE.replace(" water=1", "")
    data = load_map(_generate(tmp_path, text))
    assert "water" not in data.layers and data.water == set()


def test_loader_reads_water_from_layer_property(tmp_path: Path) -> None:
    raw = {
        "width": 2, "height": 1, "tilewidth": 16, "tileheight": 16, "tilesets": [],
        "layers": [
            {"type": "tilelayer", "name": "ground", "width": 2, "height": 1, "data": [1, 1]},
            {"type": "tilelayer", "name": "pond", "width": 2, "height": 1, "data": [0, 5],
             "properties": [{"name": "water", "type": "bool", "value": True}]},
        ],
    }
    assert parse_map(raw, tmp_path / "m.tmj").water == {(1, 0)}


def test_water_is_solid_even_without_walls(tmp_path: Path) -> None:
    text = SOURCE.replace("wall=dungeon:0,12 ", "")
    tm = TileMap.load(_generate(tmp_path, text))
    assert tm.collision.is_solid(1, 1) and tm.collision.is_solid(3, 1)
    assert not tm.collision.is_solid(2, 1)  # the word-stone between stays walkable
    assert not tm.collision.is_solid(0, 0)


def test_tint_draws_and_alternates(tmp_path: Path) -> None:
    tm = TileMap.load(_generate(tmp_path))
    assert len(tm.below_frames) == 2
    assert tm.water_frame(0.0) != tm.water_frame(WATER_FRAME_TIME + 0.01)
    assert tm.water_frame(0.0) == tm.water_frame(2 * WATER_FRAME_TIME + 0.01)
    a = pygame.Surface((80, 48))
    b = pygame.Surface((80, 48))
    tm.draw_below(a, (0, 0), now=0.0)
    tm.draw_below(b, (0, 0), now=WATER_FRAME_TIME + 0.01)
    water_px = [(16 + x, 16 + y) for x in range(16) for y in range(16)]
    assert any(a.get_at(p) != b.get_at(p) for p in water_px)  # the ripple moved
    land = [(x, y) for x in range(16) for y in range(16)]
    assert all(a.get_at(p) == b.get_at(p) for p in land)  # dry tiles never change
    # the tint shifts water towards blue compared with the untinted rubble
    plain = TileMap.load(_generate(tmp_path, SOURCE.replace(" water=1", "")))
    c = pygame.Surface((80, 48))
    plain.draw_below(c, (0, 0))
    assert a.get_at((17, 30)).b > c.get_at((17, 30)).b


def test_dry_map_has_a_single_frame(tmp_path: Path) -> None:
    tm = TileMap.load(_generate(tmp_path, SOURCE.replace(" water=1", "")))
    assert len(tm.below_frames) == 1 and tm.water_frame(5.0) == 0
    tm.draw_below(pygame.Surface((80, 48)), (0, 0))


@pytest.mark.parametrize("name", ["echo_vale", "looping_mire", "stacks", "crossroads"])
def test_story_water_is_marked(name: str) -> None:
    tm = TileMap.load(MAPS / f"{name}.tmj")
    assert tm.water, f"{name} has no water"
    assert all(tm.collision.is_solid(tx, ty) for tx, ty in tm.water)
    ground = tm.data.layers["ground"]
    # word-stones / bridges (dungeon 37, 24) are never water
    stones = {i for i, g in enumerate(ground.data) if g - 133 in (24, 37)}
    assert not any((i % tm.width, i // tm.width) in tm.water for i in stones)
