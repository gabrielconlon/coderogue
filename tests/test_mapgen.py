"""Generated story maps: mapgen round-trips, and every map's links resolve to real content."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

import pytest

from coderogue.puzzles import load_all
from coderogue.story.dialogue import DialogueBank
from coderogue.world.loader import MapData, load_map

REPO = Path(__file__).resolve().parent.parent
MAPS = REPO / "content" / "maps"
SRC = MAPS / "src"
STORY_MAPS = (
    "little_tilde_scriptorium",
    "little_tilde",
    "echo_vale",
    "crossroads",
    "hall_of_echoes",
    "branchwood",
    "looping_mire",
    "mire_heart",
    "grand_directory",
    "stacks",
    "census_hall",
    "top_gate",
)
# Map property `chapter` -> the dialogue file that voices that chapter's NPCs.
CHAPTER_DIALOGUE = {0: "little_tilde", 1: "echo_vale", 2: "branchwood_mire", 3: "grand_directory"}
ENEMY_KINDS = {"typo_mite", "off_by_one", "leak", "looper", "null_wisp", "stamp_golem", "boss"}


def _load_mapgen() -> ModuleType:
    spec = importlib.util.spec_from_file_location("mapgen", REPO / "tools" / "mapgen.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["mapgen"] = module
    spec.loader.exec_module(module)
    return module


mapgen = _load_mapgen()


def _map(name: str) -> MapData:
    return load_map(MAPS / f"{name}.tmj")


@pytest.fixture(scope="module")
def puzzles() -> dict[str, object]:
    return dict(load_all(REPO / "content" / "puzzles"))


# ---- the generator --------------------------------------------------------------------
def test_every_story_map_has_a_source() -> None:
    stems = {p.stem for p in mapgen.default_sources()}
    assert set(STORY_MAPS) <= stems


def test_check_mode_passes() -> None:
    assert mapgen.check(mapgen.default_sources()) == []
    assert mapgen.main(["--check"]) == 0


def test_check_mode_detects_stale_output(tmp_path: Path) -> None:
    src = SRC / "hall_of_echoes.map"
    mapgen.generate(src, tmp_path)
    stale = tmp_path / "hall_of_echoes.tmj"
    stale.write_text(stale.read_text(encoding="utf-8").replace('"Grubble"', '"Grumble"'))
    problems = mapgen.check([src], tmp_path)
    assert len(problems) == 1 and "stale" in problems[0]


def test_generation_is_deterministic(tmp_path: Path) -> None:
    a, b = tmp_path / "a", tmp_path / "b"
    a.mkdir()
    b.mkdir()
    src = SRC / "echo_vale.map"
    assert mapgen.generate(src, a).read_bytes() == mapgen.generate(src, b).read_bytes()


def test_parse_small_source(tmp_path: Path) -> None:
    text = """\
name: tiny
area: Tiny Room
chapter: 2
tilesets: town dungeon
legend:
  . ground=town:0,1,2
  # ground=dungeon:48 wall=dungeon:40,57
  A ground=town:25
grid:
####
#.A#
####
objects:
player_spawn spawn 1 1
altar shrine @A puzzle=ch0-01 lit=false weight=1.5 label="two words"
"""
    path = tmp_path / "tiny.map"
    path.write_text(text)
    out = mapgen.generate(path, tmp_path)
    data = load_map(out)
    assert (data.width, data.height) == (4, 3)
    assert [t.firstgid for t in data.tilesets] == [1, 133]
    walls = data.layers["walls"].data
    # bare "57" after "dungeon:40" stays on the dungeon sheet
    assert all(g in (133 + 40, 133 + 57) for g in walls if g) and walls[5] == 0
    assert data.layers["ground"].gid_at(2, 1) == 1 + 25
    altar = data.first_object("altar")
    assert altar is not None and (altar.x, altar.y) == (32, 16)
    assert altar.properties == {"puzzle": "ch0-01", "lit": False, "weight": 1.5,
                                "label": "two words"}
    assert data.properties == {"name": "tiny", "area": "Tiny Room", "chapter": 2}


def test_parse_errors(tmp_path: Path) -> None:
    bad = "tilesets: town\nlegend:\n  . ground=town:0\ngrid:\n..\n.x\nobjects:\n"
    with pytest.raises(mapgen.MapSourceError, match="not in the legend"):
        mapgen.parse_source(bad, tmp_path / "bad.map")
    ragged = "tilesets: town\nlegend:\n  . ground=town:0\ngrid:\n..\n.\nobjects:\n"
    with pytest.raises(mapgen.MapSourceError, match="width"):
        mapgen.parse_source(ragged, tmp_path / "bad.map")
    oob = "tilesets: town\nlegend:\n  . ground=town:999\ngrid:\n.\nobjects:\n"
    with pytest.raises(mapgen.MapSourceError, match="out of range"):
        mapgen.parse_source(oob, tmp_path / "bad.map")


# ---- the story maps -------------------------------------------------------------------
@pytest.mark.parametrize("name", STORY_MAPS)
def test_map_loads_with_named_spawn_first(name: str) -> None:
    data = _map(name)
    spawns = data.objects_of_type("player_spawn")
    assert spawns and spawns[0].name == "spawn", "the default spawn must be the first one"
    assert data.properties.get("area")
    assert set(data.layers) >= {"ground", "walls"}


@pytest.mark.parametrize("name", STORY_MAPS)
def test_objects_sit_on_walkable_tiles(name: str) -> None:
    data = _map(name)
    walls = data.layers["walls"]
    # npcs may stand "in" a wall-mounted prop (the ink shelf); everything else must be reachable
    for obj in data.objects:
        if obj.type == "npc":
            continue
        tx, ty = int(obj.x) // 16, int(obj.y) // 16
        assert walls.gid_at(tx, ty) == 0, f"{name}: {obj.type} {obj.name!r} is inside a wall"


@pytest.mark.parametrize("name", STORY_MAPS)
def test_doors_lead_to_existing_spawns(name: str) -> None:
    data = _map(name)
    doors = data.objects_of_type("door")
    assert any(d.properties.get("target") for d in doors), f"{name} has no exits"
    plates = {o.name for o in data.objects_of_type("plate")}
    for door in doors:
        target = door.properties.get("target")
        if not target:  # an in-map gate (see coderogue/entities/door.py)
            plate = door.properties.get("plate")
            assert not plate or plate in plates, f"{name}: gate {door.name!r} -> no plate {plate}"
            continue
        target_path = MAPS / f"{target}.tmj"
        assert target_path.exists(), f"{name}: door {door.name!r} -> missing map {target}"
        spawn = door.properties.get("spawn", "spawn")
        names = {o.name for o in load_map(target_path).objects_of_type("player_spawn")}
        assert spawn in names, f"{name}: door {door.name!r} -> {target} has no spawn {spawn!r}"


@pytest.mark.parametrize("name", STORY_MAPS)
def test_altar_and_door_puzzles_exist(name: str, puzzles: dict[str, object]) -> None:
    data = _map(name)
    for obj in data.objects:
        if obj.type == "altar":
            assert obj.properties.get("puzzle") in puzzles, f"{name}: altar {obj.name!r}"
        if "requires_solved" in obj.properties:
            assert obj.properties["requires_solved"] in puzzles, f"{name}: {obj.name!r}"


@pytest.mark.parametrize("name", STORY_MAPS)
def test_enemies_have_known_kinds(name: str) -> None:
    for enemy in _map(name).objects_of_type("enemy"):
        assert enemy.properties.get("kind") in ENEMY_KINDS, enemy.name


@pytest.mark.parametrize("name", STORY_MAPS)
def test_npcs_have_dialogue(name: str) -> None:
    data = _map(name)
    chapter = int(data.properties.get("chapter", -1))
    stem = CHAPTER_DIALOGUE.get(chapter)
    keys = sorted(
        {str(o.properties.get("dialogue") or o.name).strip().lower()
         for o in data.objects_of_type("npc")}
    )
    if stem is None or not (REPO / "content" / "dialogue" / f"{stem}.yaml").exists():
        pytest.skip(f"no dialogue file for chapter {chapter} yet; npcs: {', '.join(keys)}")
    bank = DialogueBank.load_default()
    missing = [k for k in keys if not bank.for_npc(k)]
    assert not missing, f"{name}: npcs without dialogue: {missing}"


def test_story_beats_are_placed() -> None:
    tilde = _map("little_tilde")
    assert {o.properties["puzzle"] for o in tilde.objects_of_type("altar")} == {
        "ch0-01", "ch0-02", "ch0-03"}
    assert len([e for e in tilde.objects_of_type("enemy")
                if e.properties["kind"] == "typo_mite"]) == 3
    gate = next(d for d in tilde.objects_of_type("door") if d.properties["target"] == "echo_vale")
    assert gate.properties["requires_solved"] == "ch0-03"
    assert {o.name for o in tilde.objects_of_type("waystone")} == {"tilde"}

    vale_altars = {o.properties["puzzle"] for o in _map("echo_vale").objects_of_type("altar")}
    assert vale_altars == {f"ch1-0{i}" for i in range(1, 7)}
    cross = _map("crossroads")
    assert {o.properties["puzzle"] for o in cross.objects_of_type("altar")} == {"ch1-07"}
    hall = _map("hall_of_echoes")
    lecterns = hall.objects_of_type("altar")
    assert sorted(o.name for o in lecterns) == ["lectern_a", "lectern_b", "lectern_c"]
    assert {o.properties["puzzle"] for o in lecterns} == {"ch1-b"}
    boss = hall.first_object("enemy")
    assert boss is not None and boss.name == "Grubble"
    assert boss.properties["boss"] == "grubble"


def test_chapter3_beats_are_placed() -> None:
    def puzzles_in(name: str) -> set[str]:
        return {o.properties["puzzle"] for o in _map(name).objects_of_type("altar")}

    assert puzzles_in("grand_directory") == {"ch3-01", "ch3-02", "ch3-03"}
    assert puzzles_in("stacks") == {f"ch3-0{i}" for i in range(4, 8)}
    assert puzzles_in("census_hall") == {"ch3-b"}
    directory = _map("grand_directory")
    assert [o.name for o in directory.objects_of_type("waystone")] == ["directory"]
    golems = [e for e in directory.objects_of_type("enemy")
              if e.properties["kind"] == "stamp_golem"]
    assert len(golems) == 2
    assert any(d.properties.get("requires_solved") == "ch3-03"
               for d in directory.objects_of_type("door"))
    stacks = _map("stacks")
    kinds = [e.properties["kind"] for e in stacks.objects_of_type("enemy")]
    assert kinds.count("null_wisp") == 3 and kinds.count("off_by_one") == 2
    census = next(d for d in stacks.objects_of_type("door")
                  if d.properties.get("target") == "census_hall")
    assert census.properties["requires_solved"] == "ch3-07"
    assert len(stacks.objects_of_type("liftable")) == 2
    hall = _map("census_hall")
    assert sorted(o.name for o in hall.objects_of_type("altar")) == [
        "lectern_a", "lectern_b", "lectern_c", "lectern_d"]
    boss = hall.first_object("enemy")
    assert boss is not None and boss.properties["boss"] == "hollow_archivist"
    gate = _map("top_gate")
    road = next(d for d in gate.objects_of_type("door") if d.name == "road_to_rootholm")
    assert road.properties["locked_by"] == "mvp_end"
    assert [o.name for o in gate.objects_of_type("waystone")] == ["top_gate"]


def test_chapter2_beats_are_placed() -> None:
    def puzzles_in(name: str) -> set[str]:
        return {o.properties["puzzle"] for o in _map(name).objects_of_type("altar")}

    gate = next(d for d in _map("crossroads").objects_of_type("door")
                if d.properties.get("target") == "branchwood")
    assert gate.properties["requires_solved"] == "ch1-b"
    wood = _map("branchwood")
    assert puzzles_in("branchwood") == {"ch2-01", "ch2-02"}
    assert {o.name for o in wood.objects_of_type("npc")} == {"sable", "crow_letter"}
    assert [o.name for o in wood.objects_of_type("waystone")] == ["branchwood"]
    kinds = [e.properties["kind"] for e in wood.objects_of_type("enemy")]
    assert kinds.count("null_wisp") >= 2 and kinds.count("looper") >= 2
    mire = _map("looping_mire")
    assert puzzles_in("looping_mire") == {f"ch2-0{i}" for i in range(3, 8)}
    assert {o.name for o in mire.objects_of_type("npc")} == {
        "ono", "cole_mire", "mire_traveler_a", "mire_traveler_b", "mire_traveler_c"}
    assert [o.name for o in mire.objects_of_type("waystone")] == ["mire"]
    kinds = [e.properties["kind"] for e in mire.objects_of_type("enemy")]
    assert 4 <= kinds.count("looper") <= 6
    assert kinds.count("typo_mite") == 4 and kinds.count("leak") == 2
    heart_door = next(d for d in mire.objects_of_type("door")
                      if d.properties.get("target") == "mire_heart")
    assert heart_door.properties["requires_solved"] == "ch2-06"
    heart = _map("mire_heart")
    stones = heart.objects_of_type("altar")
    assert sorted(o.name for o in stones) == ["loop_stone_a", "loop_stone_b", "loop_stone_c"]
    assert {o.properties["puzzle"] for o in stones} == {"ch2-b"}
    boss = heart.first_object("enemy")
    assert boss is not None and boss.name == "Ouroboros"
    assert boss.properties["boss"] == "ouroboros"
    onward = next(d for d in heart.objects_of_type("door")
                  if d.properties.get("target") == "grand_directory")
    assert onward.properties["requires_solved"] == "ch2-b"

@pytest.mark.parametrize("name", STORY_MAPS)
def test_headless_smoke(name: str) -> None:
    from coderogue.app import main

    assert main(["--headless-frames", "30", "--map", str(MAPS / f"{name}.tmj"), "--new"]) == 0
