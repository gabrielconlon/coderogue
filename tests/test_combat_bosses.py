"""Bosses (Grubble, Ouroboros, Hollow Archivist) against a minimal fake world."""

from __future__ import annotations

import math
from types import SimpleNamespace
from typing import Any

import pygame
import pytest

from coderogue.entities import combat
from coderogue.entities.boss import (
    ARCHIVIST_HITS_TO_EXPOSE,
    ARCHIVIST_TELEPORT,
    DEFLATE_TIME,
    GRUBBLE_MAX_MITES,
    GRUBBLE_SPAWN_INTERVAL,
    GRUBBLE_STUN,
    GRUBBLE_TELEGRAPH,
    OURO_GLOW_INTERVAL,
    OURO_SEGMENTS,
    Card,
    Grubble,
    HollowArchivist,
    Ouroboros,
    arena_for,
)
from coderogue.entities.enemies import TILE, TypoMite, spawn_enemy
from coderogue.entities.player import Player
from coderogue.world.collision import CollisionGrid
from coderogue.world.loader import MapObject

DT = 1 / 60


def room(w: int = 24, h: int = 18) -> CollisionGrid:
    rows = ["#" * w] + ["#" + "." * (w - 2) + "#" for _ in range(h - 2)] + ["#" * w]
    return CollisionGrid.from_rows(rows)


def fake_world(player_at: tuple[float, float]) -> SimpleNamespace:
    player = Player(0, 0)
    player.place_center(*player_at)
    player.iframes = 1e9  # keep contact damage out of the way
    world = SimpleNamespace(collision=room(), player=player, enemies=[], locked_target=None)
    world.killed = []
    world.on_enemy_killed = world.killed.append
    return world


ARENA = pygame.Rect(TILE, TILE, 22 * TILE, 16 * TILE)


def make_grubble(world: SimpleNamespace, at: tuple[float, float] = (192, 144)) -> Grubble:
    boss = Grubble(0, 0, arena=ARENA)
    boss.place_center(*at)
    world.enemies.append(boss)
    return boss


def run(world: SimpleNamespace, seconds: float) -> None:
    for _ in range(round(seconds / DT)):
        combat.update_enemies(world, DT)


def strike_all_letters(world: SimpleNamespace, boss: Grubble) -> None:
    for letter in list(boss.letters):
        boss.letter_cooldown = 0
        assert combat.resolve_player_attacks(world, letter.box, 1, "strike") == [letter]


# ---- factory ------------------------------------------------------------------------------
@pytest.mark.parametrize(
    ("kind", "cls"),
    [("grubble", Grubble), ("ouroboros", Ouroboros), ("hollow_archivist", HollowArchivist),
     ("archivist", HollowArchivist)],
)
def test_spawn_boss_kinds(kind: str, cls: type) -> None:
    obj = MapObject(1, "boss", "enemy", 64, 48, 20 * TILE, 12 * TILE, {"kind": kind})
    boss = spawn_enemy(obj)
    assert type(boss) is cls
    assert boss.arena == pygame.Rect(64, 48, 20 * TILE, 12 * TILE)


def test_arena_for_point_object_defaults() -> None:
    obj = MapObject(1, "boss", "enemy", 200, 200, 16, 16, {"arena_w": 10, "arena_h": 6})
    assert arena_for(obj) == pygame.Rect(208 - 80, 208 - 48, 160, 96)


# ---- Grubble ------------------------------------------------------------------------------
def test_grubble_telegraphs_then_charges_along_the_players_row() -> None:
    world = fake_world(player_at=(320, 150))
    boss = make_grubble(world, (120, 144))
    boss.charge_cooldown = 0
    combat.update_enemies(world, DT)
    assert boss.state == "telegraph" and boss.charge_dir == (1, 0)
    start = boss.center
    for _ in range(round(GRUBBLE_TELEGRAPH / DT) - 1):
        combat.update_enemies(world, DT)
        assert boss.state == "telegraph"
        assert boss.center == start  # wind-up: no movement
    combat.update_enemies(world, DT)
    assert boss.state == "charge"
    combat.update_enemies(world, DT)
    assert boss.center[0] > start[0] and boss.center[1] == start[1]
    run(world, 2.0)
    assert boss.state in ("recover", "idle")
    assert boss.rect.right <= ARENA.right


def test_grubble_charges_vertically_when_player_is_in_his_column() -> None:
    world = fake_world(player_at=(126, 40))
    boss = make_grubble(world, (120, 200))
    boss.charge_cooldown = 0
    combat.update_enemies(world, DT)
    assert boss.charge_dir == (0, -1)


def test_grubble_spawns_two_mites_every_eight_seconds_capped_at_six() -> None:
    world = fake_world(player_at=(330, 260))
    boss = make_grubble(world)
    boss.speed = 0
    boss.charge_cooldown = 1e9
    run(world, GRUBBLE_SPAWN_INTERVAL - 0.1)
    assert sum(isinstance(e, TypoMite) for e in world.enemies) == 0
    run(world, 0.2)
    mites = [e for e in world.enemies if isinstance(e, TypoMite)]
    assert len(mites) == 2 and all(m.spawned_by is boss for m in mites)
    run(world, GRUBBLE_SPAWN_INTERVAL * 4)
    assert boss.alive_minions(world) == GRUBBLE_MAX_MITES


def test_crown_letters_stun_and_gate_lecterns() -> None:
    world = fake_world(player_at=(330, 260))
    boss = make_grubble(world)
    assert not any(boss.open_lectern(i) for i in range(3))
    first = boss.letters[0]
    boss.letter_cooldown = 0
    # one swing covering every letter only knocks off one
    hits = combat.resolve_player_attacks(world, (0, 0, 400, 300), 1, "strike")
    assert sum(1 for h in hits if h in boss.letters) == 1 and not boss.stunned
    first.struck = False
    strike_all_letters(world, boss)
    assert boss.stunned
    assert boss.open_lectern(0) and not boss.open_lectern(1)
    assert boss.hazards() == []  # harmless while dazed
    boss.phase_solved(0)
    assert not boss.open_lectern(0)
    assert boss.open_lectern(1)  # still stunned: next lectern
    run(world, GRUBBLE_STUN + 0.1)
    assert not boss.stunned and not boss.open_lectern(1)
    assert not any(c.struck for c in boss.letters)  # crown regrew


def test_grubble_deflates_on_third_solve() -> None:
    world = fake_world(player_at=(330, 260))
    boss = make_grubble(world)
    for i in range(3):
        run(world, GRUBBLE_STUN + 0.1 if i else 0.1)  # wait out the previous stun
        strike_all_letters(world, boss)
        assert boss.open_lectern(i)
        boss.phase_solved(i)
    assert boss.dying and boss.alive
    assert not boss.hurt(99, world.player)
    run(world, DEFLATE_TIME - 0.1)
    assert boss.alive
    run(world, 0.2)
    assert not boss.alive and world.killed == [boss]
    combat.reap(world)
    assert boss not in world.enemies and world.killed == [boss]


# ---- Ouroboros ----------------------------------------------------------------------------
def make_ouro(world: SimpleNamespace, speed: float = 60.0) -> Ouroboros:
    boss = Ouroboros(0, 0, arena=ARENA, speed=speed)
    world.enemies.append(boss)
    return boss


def test_ouroboros_segments_follow_the_ring() -> None:
    world = fake_world(player_at=(30, 30))
    boss = make_ouro(world)
    assert len(boss.segments) == OURO_SEGMENTS
    run(world, 1.0)
    cx, cy = boss.ring_center
    for s in [boss, *boss.segments]:
        sx, sy = s.center
        assert math.hypot(sx - cx, sy - cy) == pytest.approx(boss.radius)


def test_ouroboros_regrows_every_lap_until_three_solved() -> None:
    world = fake_world(player_at=(30, 30))
    boss = make_ouro(world)
    lap = 2 * math.pi * boss.radius / boss.speed
    seg = boss.segments[3]
    assert seg.hurt(1, world.player, kind="strike") and seg.severed
    assert seg not in boss.targets()
    run(world, lap * 0.5)
    assert seg.severed
    run(world, lap * 0.6)
    assert boss.laps == 1 and not seg.severed
    boss.solved = {0, 1, 2}  # set directly so it doesn't deflate mid-test
    seg.hurt(1, world.player, kind="strike")
    run(world, lap * 1.05)
    assert seg.severed


def test_ouroboros_glow_cycles_and_cleave_opens_a_stone() -> None:
    world = fake_world(player_at=(30, 30))
    boss = make_ouro(world)
    run(world, OURO_GLOW_INTERVAL + 0.05)
    glowing = [s for s in boss.segments if s.glowing]
    assert [s.index for s in glowing] == [0]
    run(world, OURO_GLOW_INTERVAL)
    assert [s.index for s in boss.segments if s.glowing] == [1]
    seg = boss.segments[1]
    assert not boss.open_lectern(0)
    assert seg.hurt(1, world.player, kind="cleave")
    assert boss.open_lectern(0) and boss.open_loop_stone(0)
    boss.phase_solved(0)
    assert not boss.open_lectern(0)
    # a strike on a glowing segment severs it but opens nothing
    boss.glow_next()
    target = next(s for s in boss.segments if s.glowing)
    assert target.hurt(1, world.player, kind="strike")
    assert boss.open_stone is None


def test_ouroboros_is_not_hurt_by_damage_and_deflates_after_three_stones() -> None:
    world = fake_world(player_at=(30, 30))
    boss = make_ouro(world)
    assert not boss.hurt(50, world.player, kind="cleave")
    for i in range(3):
        boss.phase_solved(i)
    assert boss.dying
    run(world, DEFLATE_TIME + 0.1)
    assert not boss.alive and world.killed == [boss]


# ---- Hollow Archivist ---------------------------------------------------------------------
def test_archivist_teleports_and_throws_cards_that_die_on_walls() -> None:
    world = fake_world(player_at=(48, 200))
    boss = HollowArchivist(0, 0, arena=ARENA)
    boss.place_center(*ARENA.center)
    world.enemies.append(boss)
    run(world, ARCHIVIST_TELEPORT + 0.05)
    assert boss.point_index == 0 and boss.center == boss.points[0]
    assert len(boss.cards) == 1
    run(world, ARCHIVIST_TELEPORT)
    assert boss.point_index == 1
    card = Card(40, 40, -200, 0)
    card.update(DT, world)
    assert card.alive
    for _ in range(30):
        card.update(DT, world)
    assert not card.alive  # despawned against the left wall


def test_archivist_card_hurts_player_and_vanishes() -> None:
    world = fake_world(player_at=(100, 100))
    world.player.iframes = 0
    boss = HollowArchivist(0, 0, arena=ARENA)
    boss.place_center(300, 200)
    world.enemies.append(boss)
    card = Card(0, 0, 0, 0)
    card.place_center(*world.player.center)
    boss.cards.append(card)
    hp = world.player.hp
    assert combat.resolve_contacts(world) == 1
    assert world.player.hp == hp - 1 and not card.alive


def test_archivist_exposed_after_strikes_opens_lectern() -> None:
    world = fake_world(player_at=(30, 30))
    boss = HollowArchivist(0, 0, arena=ARENA)
    world.enemies.append(boss)
    combat.update_enemies(world, DT)
    for _ in range(ARCHIVIST_HITS_TO_EXPOSE):
        boss.iframes = 0
        assert boss.hurt(1, world.player)
    assert boss.stunned and boss.open_lectern(0)


def test_boss_draw_smoke() -> None:
    surface = pygame.Surface((400, 300))
    world: Any = fake_world(player_at=(30, 30))
    sprite = pygame.Surface((16, 16), pygame.SRCALPHA)
    for boss in (Grubble(100, 100, sprite, arena=ARENA), Ouroboros(0, 0, sprite, arena=ARENA),
                 HollowArchivist(0, 0, sprite, arena=ARENA)):
        world.enemies.append(boss)
        boss.update(DT, world)
        boss.draw(surface, (0, 0))
        boss.deflate()
        boss.draw(surface, (0, 0))
