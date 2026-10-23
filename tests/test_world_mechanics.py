"""Phase 5b world mechanics: doors, waystones, items, lock-on, cleave, rewind, lift, search,
marks."""

from __future__ import annotations

import pygame
import pytest

from coderogue.app import Game, resource_path
from coderogue.entities import player as P
from coderogue.entities.enemies import Wanderer
from coderogue.entities.waystone import WaystoneMenu
from coderogue.input.modes import Mode
from coderogue.world.scene import WorldScene
from coderogue.world.transitions import FADE_TIME, map_ref, resolve_map

ROOM1 = resource_path("content", "maps", "test_room.tmj")
DT = 1 / 60


@pytest.fixture
def game(tmp_path, monkeypatch):
    monkeypatch.setenv("CODEROGUE_HOME", str(tmp_path))
    monkeypatch.setenv("CODEROGUE_ALL_UNLOCKED", "1")  # these tests exercise every stance
    g = Game(headless=True)
    yield g
    pygame.quit()


@pytest.fixture
def world(game):
    ws = WorldScene(game, ROOM1)
    game.push(ws)
    return ws


def key(k: int, uni: str = "") -> pygame.event.Event:
    return pygame.event.Event(pygame.KEYDOWN, key=k, unicode=uni, mod=0)


def press(ws: WorldScene, ch: str) -> None:
    ws.handle_event(key(pygame.key.key_code(ch) if ch.isalnum() else 0, ch))


def steps(game: Game, seconds: float) -> None:
    for _ in range(round(seconds / DT)):
        game.step()


def calm_enemies(ws: WorldScene) -> None:
    for e in ws.enemies:
        e.speed = 0
        if hasattr(e, "direction"):
            e.direction = (0, 0)
        if hasattr(e, "turn_timer"):
            e.turn_timer = 999


def make_enemy(ws: WorldScene, cx: float, cy: float, name: str = "bug") -> Wanderer:
    e = Wanderer(0, 0, None, hp=3, speed=0, name=name)
    e.turn_timer = 999
    e.place_center(cx, cy)
    ws.enemies.append(e)
    return e


def go_room2(game: Game, ws: WorldScene) -> None:
    ws.player.iframes = 99
    door = next(d for d in ws.doors if d.name == "east_door")
    steps(game, 0.1)  # arm doors (the hero starts off them)
    ws.player.place_center(*door.center)
    steps(game, 2 * FADE_TIME + 0.1)


# ---- maps and doors -------------------------------------------------------------------
def test_map_refs_round_trip():
    assert map_ref(ROOM1) == "test_room"
    assert resolve_map("test_room") == ROOM1


def test_door_transition_loads_in_place_and_places_player(game, world):
    assert world.area_name == "Test Room"
    assert "entered:test_room" in game.progress.flags
    go_room2(game, world)
    assert game.scene is world
    assert world.map_key == "test_room2"
    assert world.area_name == "Test Annex" and world.area_card.visible
    spawn = next(o for o in world.tilemap.data.objects if o.name == "from_room1")
    assert world.player.center == pytest.approx(spawn.center)
    assert not world.fade.active
    # arriving next to the return door does not bounce straight back
    steps(game, 0.5)
    assert world.map_key == "test_room2"


def test_locked_door_blocks_and_flashes(game, world):
    world.load_map("test_room2", "from_room1")
    door = next(d for d in world.doors if d.name == "null_door")
    assert door.locked
    ts = world.tilemap.tile_size
    tx, ty = door.tiles(ts)[0]
    assert world.collision.is_solid(tx, ty)
    world.player.place_center(door.center[0], door.y - 6)
    steps(game, 0.1)
    assert "Null holds this door" in world.message
    assert world.map_key == "test_room2"
    game.progress.flags.add("never_set_flag")
    steps(game, DT)
    assert not door.locked and not world.collision.is_solid(tx, ty)


# ---- waystones and death --------------------------------------------------------------
def test_waystone_menu_sets_last_waystone_and_death_respawns(game, world):
    world.load_map("test_room2", "from_room1")
    stone = world.waystones[0]
    world.player.place_center(*stone.center)
    world.player.hp = 1
    world.player.u_charges = 0
    world.handle_event(key(pygame.K_i, "i"))
    menu = game.scene
    assert isinstance(menu, WaystoneMenu)
    assert world.last_waystone == ("test_room2", "annex_stone")
    menu.handle_event(key(pygame.K_j, "j"))
    menu.handle_event(key(pygame.K_j, "j"))
    assert menu.choice == "rest"
    menu.handle_event(key(pygame.K_RETURN, "\r"))
    assert game.scene is world
    assert world.player.hp == world.player.max_hp and world.player.u_charges == P.MAX_U_CHARGES
    # die back in room 1: wake at the annex waystone with everything kept
    world.load_map("test_room")
    world.player.coins = 7
    game.progress.xp = 30
    world.player.hp = 0
    game.step()
    assert world.map_key == "test_room2"
    assert world.player.center == pytest.approx(stone.stand_point)
    assert world.player.hp == world.player.max_hp
    assert world.player.coins == 7 and game.progress.xp == 30


def test_waystone_seal_saves_extras(game, world):
    world.load_map("test_room2", "from_room1")
    world.player.coins = 12
    world.use_waystone(world.waystones[0])
    game.scene.pick("seal")
    state = game.saves.load("slot1")
    assert state is not None and state.map == "test_room2"
    assert state.waystone == "annex_stone"
    assert state.progress["world"]["coins"] == 12
    assert state.progress["world"]["last_waystone"] == ["test_room2", "annex_stone"]
    fresh = Game(headless=True)
    w2 = WorldScene(fresh, ROOM1)
    from coderogue.app import _restore_save

    _restore_save(fresh, w2)
    assert w2.map_key == "test_room2" and w2.player.coins == 12
    assert w2.last_waystone == ("test_room2", "annex_stone")


# ---- items ----------------------------------------------------------------------------
def test_chest_opens_once_and_is_remembered(game, world):
    world.load_map("test_room2", "from_room1")
    chest = next(c for c in world.chests if c.name == "annex_chest")
    world.player.place_center(chest.center[0], chest.center[1] + 14)
    world.handle_event(key(pygame.K_i, "i"))
    assert chest.opened and world.player.coins == 5 and world.player.items == ["spyglass"]
    world.handle_event(key(pygame.K_i, "i"))
    assert world.player.coins == 5 and world.player.items == ["spyglass"]
    world.load_map("test_room2", "from_room1")
    again = next(c for c in world.chests if c.name == "annex_chest")
    assert again.opened and again.open() is None


def test_potion_heals_and_coin_adds(game, world):
    world.load_map("test_room2", "from_room1")
    potion = next(p for p in world.pickups if p.kind == "potion")
    coin = next(p for p in world.pickups if p.kind == "coin")
    world.player.place_center(*potion.center)
    steps(game, DT)
    assert potion in world.pickups  # full health: left on the floor
    world.player.hp = 2
    steps(game, DT)
    assert world.player.hp == 4 and potion not in world.pickups
    world.player.place_center(*coin.center)
    steps(game, DT)
    assert world.player.coins == 3 and coin not in world.pickups
    world.load_map("test_room2", "from_room1")
    assert not world.pickups  # taken pickups stay taken


# ---- VISUAL lock-on -------------------------------------------------------------------
def test_lock_on_picks_nearest_and_cycles(game, world):
    world.enemies.clear()
    px, py = world.player.center
    near = make_enemy(world, px + 30, py, "near")
    right = make_enemy(world, px + 80, py, "right")
    below = make_enemy(world, px + 30, py + 50, "below")
    make_enemy(world, px + 200, py, "far")
    world.handle_event(key(pygame.K_v, "v"))
    assert world.modes.mode is Mode.VISUAL and world.locked_target is near
    world.handle_event(key(pygame.K_l, "l"))
    assert world.locked_target is right
    world.handle_event(key(pygame.K_h, "h"))
    assert world.locked_target is near
    world.handle_event(key(pygame.K_j, "j"))
    assert world.locked_target is below
    assert not world.held  # hjkl cycles instead of walking
    world.draw(game.surface)
    world.handle_event(key(pygame.K_ESCAPE))
    assert world.modes.mode is Mode.NORMAL and world.locked_target is None


def test_lock_on_needs_a_bug_in_range(game, world):
    world.enemies.clear()
    world.handle_event(key(pygame.K_v, "v"))
    assert world.modes.mode is Mode.NORMAL and world.locked_target is None


# ---- dd cleave ------------------------------------------------------------------------
def test_dd_cleave_hits_the_row(game, world):
    world.enemies.clear()
    world.player.facing = (1, 0)
    px, py = world.player.center
    in_row = [make_enemy(world, px + dx, py) for dx in (-100, 40, 120)]
    off_row = make_enemy(world, px + 40, py + 40)
    world.handle_event(key(pygame.K_d, "d"))
    assert world.player.cleave_rect is None
    world.handle_event(key(pygame.K_d, "d"))
    x, y, w, h = world.player.cleave_rect
    assert (w, h) == (16 * 16, 16) and x == pytest.approx(px - 128)
    assert all(e.hp == 2 for e in in_row) and off_row.hp == 3
    # cooldown: an immediate second dd does nothing
    for e in in_row:
        e.iframes = 0
    world.handle_event(key(pygame.K_d, "d"))
    world.handle_event(key(pygame.K_d, "d"))
    assert all(e.hp == 2 for e in in_row)
    world.player.facing = (0, 1)
    assert world.player.cleave_box()[3] == 16 * 16


def test_slow_dd_is_not_a_cleave(game, world):
    world.handle_event(key(pygame.K_d, "d"))
    steps(game, 0.5)
    world.handle_event(key(pygame.K_d, "d"))
    assert world.player.cleave_rect is None


# ---- u rewind -------------------------------------------------------------------------
def test_u_rewinds_and_uses_a_charge(game, world):
    world.enemies.clear()
    world.player.place_center(40, 40)
    start = (world.player.x, world.player.y)
    world.handle_event(key(pygame.K_l, "l"))
    steps(game, 1.0)
    world.handle_event(pygame.event.Event(pygame.KEYUP, key=pygame.K_l, mod=0))
    assert world.player.x > start[0] + 50
    world.handle_event(key(pygame.K_u, "u"))
    assert world.player.u_charges == P.MAX_U_CHARGES - 1
    assert world.player.rewinding and world.player.invulnerable
    steps(game, P.REWIND_TIME + 0.05)
    assert not world.player.rewinding
    assert (world.player.x, world.player.y) == pytest.approx(start, abs=1.0)
    world.player.u_charges = 0
    steps(game, 0.5)
    world.handle_event(key(pygame.K_u, "u"))
    assert not world.player.rewinding and "hourglass" in world.message


# ---- yy / p and plates ----------------------------------------------------------------
def test_yank_put_and_plate_opens_gate(game, world):
    world.load_map("test_room2", "from_room1")
    calm_enemies(world)
    crate = world.liftables[0]
    plate = world.plates[0]
    gate = next(d for d in world.doors if d.name == "annex_gate")
    assert gate.locked
    # stand left of the crate, facing it
    world.player.place_center(crate.center[0] - 13, crate.center[1])
    world.player.facing = (1, 0)
    world.handle_event(key(pygame.K_y, "y"))
    world.handle_event(key(pygame.K_y, "y"))
    assert world.player.carrying is crate and crate not in world.liftables
    world.draw(game.surface)
    # stand left of the plate and put it down
    world.player.place_center(plate.center[0] - 13, plate.center[1])
    world.handle_event(key(pygame.K_p, "p"))
    assert world.player.carrying is None and crate in world.liftables
    assert crate.center == plate.center
    steps(game, DT)
    assert plate.pressed and not gate.locked
    ts = world.tilemap.tile_size
    assert not world.collision.is_solid(*gate.tiles(ts)[0])
    assert world.collision.is_solid(*crate.tile(ts))


def test_put_refuses_a_wall(game, world):
    world.load_map("test_room2", "from_room1")
    world.player.carrying = world.liftables.pop()
    world.player.place_center(21, 40)
    world.player.facing = (-1, 0)
    world.handle_event(key(pygame.K_p, "p"))
    assert world.player.carrying is not None


# ---- / search and n -------------------------------------------------------------------
def test_search_highlights_and_n_cycles(game, world):
    world.load_map("test_room2", "from_room1")
    world.handle_event(key(pygame.K_SLASH, "/"))
    assert world.search_input == ""
    for ch in "chest":
        world.handle_event(key(pygame.key.key_code(ch), ch))
    world.handle_event(key(pygame.K_RETURN, "\r"))
    assert world.search_input is None
    names = sorted(e.name for e in world.search_matches)
    assert names == ["annex_chest", "vault_chest"]
    first = world.search_next()
    second = world.search_next()
    assert {first.name, second.name} == set(names) and first is not second
    assert world.search_next() is first
    assert world.focus is first
    world.draw(game.surface)
    world.handle_event(key(pygame.K_ESCAPE))
    assert world.search_matches == [] and world.current_match is None
    assert world.search("zzz") == 0


# ---- marks ----------------------------------------------------------------------------
def test_marks_fast_travel(game, world):
    world.enemies.clear()
    world.handle_event(key(pygame.K_m, "m"))
    world.handle_event(key(pygame.K_a, "a"))
    assert "a" not in world.marks  # not at a waystone
    stone = world.waystones[0]
    world.player.place_center(*stone.center)
    world.handle_event(key(pygame.K_m, "m"))
    world.handle_event(key(pygame.K_a, "a"))
    assert world.marks["a"] == ("test_room", "tilde_stone")
    world.load_map("test_room2", "from_room1")
    calm_enemies(world)
    world.enemies.clear()
    world.handle_event(key(pygame.K_QUOTE, "'"))
    world.handle_event(key(pygame.K_a, "a"))
    steps(game, 2 * FADE_TIME + 0.1)
    assert world.map_key == "test_room"
    assert world.player.center == pytest.approx(world.waystones[0].stand_point)
    # not while a bug is close
    px, py = world.player.center
    make_enemy(world, px + 20, py)
    world.handle_event(key(pygame.K_QUOTE, "'"))
    world.handle_event(key(pygame.K_a, "a"))
    assert not world.fade.active and "bugs" in world.message


def test_unknown_mark_and_unlock_gate(game, world):
    world.jump_to_mark("z")
    assert "E20" in world.message
    world.unlocked.discard("cleave")
    assert not world.cleave()


def test_draw_with_overlays(game, world):
    world.flash("hello")
    world.handle_event(key(pygame.K_SLASH, "/"))
    game.draw()
    world.handle_event(key(pygame.K_ESCAPE))
    world.travel("test_room2", "from_room1")
    steps(game, FADE_TIME / 2)
    game.draw()


# ---- bosses ---------------------------------------------------------------------------
def test_boss_object_mapping_and_altar_phase():
    from coderogue.entities.altar import Altar
    from coderogue.world.loader import MapObject
    from coderogue.world.scene import _boss_object, altar_phase

    obj = MapObject(1, "Grubble", "enemy", 0, 0, 16, 16, {"kind": "boss", "boss": "grubble"})
    assert _boss_object(obj).properties["kind"] == "grubble"
    plain = MapObject(2, "m", "enemy", 0, 0, 16, 16, {"kind": "typo_mite"})
    assert _boss_object(plain) is plain
    assert altar_phase(Altar(0, 0, properties={"phase": "b"})) == 1
    assert altar_phase(Altar(0, 0, properties={"phase": 2})) == 2
    assert altar_phase(Altar(0, 0)) is None


def test_boss_lectern_needs_a_stun(game):
    path = resource_path("content", "maps", "hall_of_echoes.tmj")
    if not path.exists():
        pytest.skip("hall_of_echoes map not present")
    from coderogue.altar import AltarScene
    from coderogue.entities.boss import Boss

    ws = WorldScene(game, path)
    game.push(ws)
    boss = ws.active_boss()
    assert isinstance(boss, Boss)
    altar = next(a for a in ws.altars if a.properties.get("phase") == "a")
    ws.on_altar(altar)
    assert game.scene is ws and "Stun" in ws.message
    boss.stun(5.0)
    ws.on_altar(altar)
    assert isinstance(game.scene, AltarScene) and game.scene.phase == 0
    game.pop()
    ws.on_boss_phase_solved(None, 0)  # type: ignore[arg-type]
    assert 0 in boss.solved
