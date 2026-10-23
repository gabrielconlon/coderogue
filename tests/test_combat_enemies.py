"""Bug roster and combat helpers, against a minimal fake world (no WorldScene)."""

from __future__ import annotations

import math
import random
from types import SimpleNamespace
from typing import Any

import pygame
import pytest

from coderogue.entities import combat
from coderogue.entities.enemies import (
    KNOCKBACK_TILES,
    LUNGE_AIM_TIME,
    SPLIT_TIME,
    TILE,
    Leak,
    Looper,
    NullWisp,
    OffByOne,
    StampGolem,
    TypoMite,
    Wanderer,
    spawn_enemy,
)
from coderogue.entities.player import Player
from coderogue.world.collision import CollisionGrid
from coderogue.world.loader import MapObject

DT = 1 / 60


def room(w: int = 16, h: int = 12) -> CollisionGrid:
    """An open room with a one-tile wall border."""
    rows = ["#" * w] + ["#" + "." * (w - 2) + "#" for _ in range(h - 2)] + ["#" * w]
    return CollisionGrid.from_rows(rows)


def fake_world(grid: CollisionGrid | None = None, player_at: tuple[float, float] = (40, 40)):
    """SimpleNamespace world with collision, player, enemies, locked_target and kill log."""
    player = Player(0, 0)
    player.place_center(*player_at)
    killed: list[Any] = []
    world = SimpleNamespace(
        collision=grid or room(), player=player, enemies=[], locked_target=None, killed=killed
    )
    world.on_enemy_killed = killed.append
    return world


def obj(kind: str | None, **props: Any) -> MapObject:
    if kind is not None:
        props["kind"] = kind
    return MapObject(1, "bug", "enemy", 96, 96, 16, 16, props)


class FakeSprites:
    TOWN_SHEET = ("town",)

    def __init__(self) -> None:
        self.calls: list[tuple[int, tuple[str, ...] | None]] = []

    def sheet_tile(self, tile: int, sheet: tuple[str, ...] | None = None) -> pygame.Surface:
        self.calls.append((tile, sheet))
        return pygame.Surface((16, 16), pygame.SRCALPHA)


# ---- factory -----------------------------------------------------------------------------
@pytest.mark.parametrize(
    ("kind", "cls", "tile"),
    [
        (None, Wanderer, 110),
        ("wanderer", Wanderer, 110),
        ("typo_mite", TypoMite, 110),
        ("off_by_one", OffByOne, 122),
        ("leak", Leak, 108),
        ("looper", Looper, 120),
        ("null_wisp", NullWisp, 121),
        ("stamp_golem", StampGolem, 94),
        ("mystery", Wanderer, 110),
    ],
)
def test_spawn_enemy_per_kind(kind: str | None, cls: type, tile: int) -> None:
    sprites = FakeSprites()
    enemy = spawn_enemy(obj(kind), sprites)
    assert type(enemy) is cls
    assert enemy.center == (104, 104)
    assert enemy.sprite is not None
    assert sprites.calls[-1][0] == tile
    if cls is StampGolem:
        assert sprites.calls[-1][1] == FakeSprites.TOWN_SHEET


def test_spawn_enemy_overrides() -> None:
    enemy = spawn_enemy(obj("leak", hp=7, speed=12.5, tile=5), FakeSprites())
    assert enemy.hp == enemy.max_hp == 7 and enemy.speed == 12.5
    assert spawn_enemy(obj("typo_mite")).hp == 1  # one hit; no sprites module is fine


def test_wanderer_keeps_legacy_call_shape() -> None:
    e = Wanderer(0, 0, hp=2)
    assert e.hurt(1, (10, 0))  # point source, default kind
    assert not e.hurt(1)
    e.iframes = 0
    assert e.hurt(1)
    assert not e.alive


# ---- behaviours ---------------------------------------------------------------------------
def test_typo_mite_dies_to_one_strike() -> None:
    world = fake_world()
    mite = spawn_enemy(obj("typo_mite"))
    world.enemies.append(mite)
    mite.update(DT, world)
    assert mite.hurt(1, world.player)
    assert not mite.alive
    assert world.killed == [mite]
    combat.reap(world)
    assert world.enemies == [] and world.killed == [mite]  # reported once


def test_off_by_one_lands_one_tile_off() -> None:
    world = fake_world(room(16, 12), player_at=(120, 88))
    bug = OffByOne(0, 0, rng=random.Random(3))
    bug.cooldown = 0
    bug.place_center(72, 88)
    world.player.iframes = 99
    bug.update(DT, world)
    assert bug.state == "aim" and bug.aim_point == (120, 88)
    start = bug.center
    for _ in range(round(LUNGE_AIM_TIME / DT) - 1):
        bug.update(DT, world)
        assert bug.state == "aim"
    assert bug.center == pytest.approx(start)  # telegraph: stands still
    for _ in range(120):
        bug.update(DT, world)
        if bug.state == "rest":
            break
    assert bug.state == "rest"
    ax, ay = bug.aim_point
    cx, cy = bug.center
    assert math.hypot(cx - ax, cy - ay) == pytest.approx(TILE)
    assert (cx, cy) == pytest.approx(bug.landing_point)
    assert cx == pytest.approx(ax)  # horizontal lunge: off by one tile vertically


def test_leak_splits_after_six_seconds_into_half_hp() -> None:
    world = fake_world(player_at=(200, 150))
    leak = Leak(0, 0, hp=4, speed=0, rng=random.Random(1))
    leak.place_center(64, 64)
    world.enemies.append(leak)
    steps = round(SPLIT_TIME / DT)
    for _ in range(steps - 5):
        combat.update_enemies(world, DT)
    assert len(world.enemies) == 1
    for _ in range(10):
        combat.update_enemies(world, DT)
    assert len(world.enemies) == 2
    assert [e.hp for e in world.enemies] == [2, 2]
    assert all(isinstance(e, Leak) for e in world.enemies)


def test_leak_split_uses_spawn_hook_and_hit_resets_timer() -> None:
    world = fake_world()
    spawned: list[Any] = []
    world.spawn_enemy_instance = spawned.append
    leak = Leak(48, 48, hp=2, speed=0)
    leak.split_timer = 1.0
    leak.update(DT, world)
    assert leak.hurt(1, None)
    assert leak.split_timer == SPLIT_TIME
    leak.hp = 2
    leak.split_timer = DT / 2
    leak.update(DT, world)
    assert len(spawned) == 1 and spawned[0].hp == 1 and leak.hp == 1
    leak.split_timer = DT / 2
    leak.update(DT, world)
    assert len(spawned) == 1  # 1 hp cannot split


def test_null_wisp_only_hittable_when_locked() -> None:
    world = fake_world()
    wisp = NullWisp(48, 48)
    wisp.update(DT, world)
    assert wisp.alpha < 255
    assert not wisp.hurt(1, world.player)
    assert wisp.hp == wisp.max_hp
    world.locked_target = wisp
    wisp.update(DT, world)
    assert wisp.alpha == 255
    assert wisp.hurt(1, world.player)
    assert wisp.hp == wisp.max_hp - 1


def test_null_wisp_through_resolve_player_attacks() -> None:
    world = fake_world()
    wisp = NullWisp(0, 0, speed=0)
    wisp.place_center(*world.player.center)
    world.enemies.append(wisp)
    box = world.player.box
    assert combat.resolve_player_attacks(world, box, 1, "strike") == []
    world.locked_target = wisp
    assert combat.resolve_player_attacks(world, box, 1, "strike") == [wisp]


def test_looper_takes_double_damage_from_cleave() -> None:
    a, b = Looper(32, 32, hp=4), Looper(32, 32, hp=4)
    assert a.hurt(1, None, kind="strike") and a.hp == 3
    assert b.hurt(1, None, kind="cleave") and b.hp == 2


def test_looper_patrols_its_row() -> None:
    world = fake_world(player_at=(200, 150))
    looper = Looper(40, 40, speed=90)
    y = looper.y
    xs = []
    for _ in range(300):
        looper.update(DT, world)
        xs.append(looper.x)
    assert looper.y == y
    assert max(xs) > 150 and min(xs) < 60


def test_stamp_golem_is_immune_and_blocks_its_tile() -> None:
    world = fake_world()
    golem = StampGolem(0, 0)
    golem.place_center(5 * TILE + 8, 3 * TILE + 8)
    golem.update(DT, world)
    assert world.collision.is_solid(5, 3)
    for kind in ("strike", "cleave", "dash"):
        assert not golem.hurt(5, world.player, kind=kind)
    assert golem.alive and golem.hp == golem.max_hp and golem.stamp_flash > 0
    world.enemies.append(golem)
    golem.dismiss(world)
    assert not world.collision.is_solid(5, 3)
    combat.reap(world)
    assert world.killed == []  # leaving is not a kill


# ---- knockback / contacts -------------------------------------------------------------------
def test_knockback_is_one_and_a_half_tiles() -> None:
    world = fake_world(player_at=(200, 150))
    e = Wanderer(0, 0, speed=0)
    e.place_center(96, 96)
    e.turn_timer = 99
    assert e.hurt(1, (80, 96))
    for _ in range(20):
        e.update(DT, world)
    assert e.center[0] == pytest.approx(96 + KNOCKBACK_TILES * TILE)
    assert e.center[1] == pytest.approx(96)


def test_knockback_blocked_by_wall() -> None:
    world = fake_world(player_at=(200, 150))
    e = Wanderer(0, 0, speed=0)
    e.turn_timer = 99
    e.place_center(TILE + 6 + 4, 96)  # just right of the left wall
    assert e.hurt(1, (e.center[0] + 10, 96))
    for _ in range(20):
        e.update(DT, world)
    assert e.x == pytest.approx(TILE)  # flush against the wall


def test_resolve_contacts_hurts_player_once_with_iframes() -> None:
    world = fake_world()
    e = Wanderer(0, 0)
    e.place_center(*world.player.center)
    world.enemies.append(e)
    hp = world.player.hp
    assert combat.resolve_contacts(world) == 1
    assert combat.resolve_contacts(world) == 0
    assert world.player.hp == hp - 1


def test_resolve_player_attacks_respects_struck_set_and_kind() -> None:
    world = fake_world()
    looper = Looper(0, 0, hp=5, speed=0)
    looper.place_center(*world.player.center)
    world.enemies.append(looper)
    struck: set[int] = set()
    box = world.player.box
    assert combat.resolve_player_attacks(world, box, 1, "cleave", struck) == [looper]
    looper.iframes = 0
    assert combat.resolve_player_attacks(world, box, 1, "cleave", struck) == []
    assert looper.hp == 3


def test_update_enemies_includes_enemies_added_mid_loop() -> None:
    world = fake_world(player_at=(200, 150))
    leak = Leak(48, 48, hp=4, speed=0)
    leak.split_timer = DT / 2
    world.enemies.append(leak)
    combat.update_enemies(world, DT)
    assert len(world.enemies) == 2
    assert world.enemies[1].split_timer < SPLIT_TIME  # the child was updated too
