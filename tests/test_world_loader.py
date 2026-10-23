import json
from pathlib import Path

import pytest

from coderogue.world.loader import FLIP_H, MapFormatError, load_map, parse_map

ROOT = Path(__file__).resolve().parent.parent
TEST_ROOM = ROOT / "content" / "maps" / "test_room.tmj"


def test_load_test_room():
    m = load_map(TEST_ROOM)
    assert (m.width, m.height, m.tilewidth) == (20, 12, 16)
    assert m.pixel_size == (320, 192)
    assert {"ground", "walls"} <= set(m.layers)
    ts = m.tilesets[0]
    assert ts.columns == 12 and ts.firstgid == 1
    assert ts.image.name == "tilemap_packed.png"
    assert ts.source_rect(57) == (9 * 16, 4 * 16, 16, 16)
    walls = m.layers["walls"]
    assert walls.gid_at(0, 0) == 58 and walls.gid_at(2, 2) == 0
    assert m.first_object("player_spawn") is not None
    assert len(m.objects_of_type("enemy")) == 2
    altar = m.first_object("altar")
    assert altar is not None and altar.properties["puzzle"] == "P-01"


def _minimal(**over):
    raw = {
        "width": 2, "height": 1, "tilewidth": 16, "tileheight": 16,
        "orientation": "orthogonal",
        "tilesets": [],
        "layers": [{"type": "tilelayer", "name": "walls", "width": 2, "height": 1,
                    "data": [FLIP_H | 5, 0]}],
    }
    raw.update(over)
    return raw


def test_flip_flags_stripped_and_tile_objects_anchor(tmp_path):
    raw = _minimal()
    raw["layers"].append({"type": "objectgroup", "name": "objects", "objects": [
        {"id": 1, "name": "a", "class": "altar", "gid": 33, "x": 16, "y": 32,
         "width": 16, "height": 16},
    ]})
    m = parse_map(raw, tmp_path / "m.tmj")
    assert m.layers["walls"].data == [5, 0]
    obj = m.objects[0]
    assert obj.type == "altar" and obj.y == 16  # bottom-left anchor converted to top-left


def test_external_tsj_tileset(tmp_path):
    (tmp_path / "ts").mkdir()
    (tmp_path / "ts" / "dungeon.tsj").write_text(json.dumps({
        "name": "d", "image": "sheet.png", "imagewidth": 192, "imageheight": 176,
        "tilewidth": 16, "tileheight": 16, "columns": 12, "tilecount": 132,
    }))
    raw = _minimal(tilesets=[{"firstgid": 1, "source": "ts/dungeon.tsj"}])
    m = parse_map(raw, tmp_path / "m.tmj")
    assert m.tilesets[0].image == (tmp_path / "ts" / "sheet.png").resolve()
    assert m.tileset_for(5) is m.tilesets[0]
    assert m.tileset_for(0) is None


def test_rejects_base64_and_infinite(tmp_path):
    raw = _minimal()
    raw["layers"][0]["encoding"] = "base64"
    with pytest.raises(MapFormatError):
        parse_map(raw, tmp_path / "m.tmj")
    with pytest.raises(MapFormatError):
        parse_map(_minimal(infinite=True), tmp_path / "m.tmj")


def test_tilemap_builds_collision_and_surfaces():
    import pygame

    from coderogue.world.tilemap import TileMap

    pygame.init()
    tm = TileMap.load(TEST_ROOM)
    assert tm.collision.is_solid(0, 0)
    assert not tm.collision.is_solid(2, 2)
    assert tm.below.get_size() == (320, 192)
    assert tm.tile_surface(58).get_size() == (16, 16)
