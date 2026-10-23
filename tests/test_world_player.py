import math
from types import SimpleNamespace

import pytest

from coderogue.entities import player as P
from coderogue.entities.enemies import Wanderer
from coderogue.entities.player import Player
from coderogue.world.collision import CollisionGrid

DT = 1 / 60


def open_world(w=40, h=40):
    return SimpleNamespace(collision=CollisionGrid.from_rows(["." * w] * h))


def run(p, world, seconds, move=(0, 0)):
    for _ in range(round(seconds / DT)):
        p.update(DT, world, move=move)


def test_walk_speed_integrates_over_fixed_dt():
    w = open_world()
    p = Player(100, 100)
    run(p, w, 1.0, move=(1, 0))
    assert p.x == pytest.approx(100 + P.SPEED, abs=1e-6)
    assert p.facing == (1, 0)


def test_diagonal_is_normalised():
    w = open_world()
    p = Player(100, 100)
    run(p, w, 1.0, move=(1, 1))
    assert math.hypot(p.x - 100, p.y - 100) == pytest.approx(P.SPEED, abs=1e-6)


def test_walk_animation_bobs_and_flips():
    w = open_world()
    p = Player(100, 100)
    bobs = set()
    for _ in range(30):
        p.update(DT, w, move=(1, 0))
        bobs.add(p.bob)
    assert bobs == {0, -1}
    assert p.flip_x == P.SPRITE_FACES_LEFT
    p.update(DT, w, move=(0, 0))
    assert p.bob == 0


def test_player_slides_along_wall():
    rows = ["#" * 10] + ["#" + "." * 8 + "#"] * 8 + ["#" * 10]
    w = SimpleNamespace(collision=CollisionGrid.from_rows(rows))
    p = Player(40, 17)
    run(p, w, 0.5, move=(1, -1))
    assert p.y == pytest.approx(16)
    assert p.x > 60


def test_dash_distance_iframes_and_cooldown():
    w = open_world()
    p = Player(100, 100)
    p.facing = (1, 0)
    assert p.dash(forward=True)
    assert p.invulnerable
    assert not p.dash()  # already dashing
    run(p, w, 0.5)
    assert p.x == pytest.approx(100 + P.DASH_TILES * 16, abs=0.01)
    assert not p.dashing
    assert not p.invulnerable
    # cooldown is ticking: still blocked right after the dash, allowed later
    p2 = Player(100, 100)
    p2.facing = (1, 0)
    p2.dash()
    dash_time = P.DASH_TILES * 16 / P.DASH_SPEED
    run(p2, w, dash_time + DT)
    assert not p2.dash()
    run(p2, w, P.DASH_COOLDOWN + DT)
    assert p2.dash()


def test_back_dash_keeps_facing_and_count_dash():
    w = open_world()
    p = Player(200, 200)
    p.facing = (1, 0)
    p.dash(forward=False)
    run(p, w, 0.5)
    assert p.x == pytest.approx(200 - P.DASH_TILES * 16, abs=0.01)
    assert p.facing == (1, 0)
    q = Player(200, 200)
    q.dash_toward((0, 1), 3)  # "3j"
    run(q, w, 0.5)
    assert q.y == pytest.approx(200 + 48, abs=0.01)
    assert q.facing == (0, 1)


def test_dash_stops_at_wall():
    rows = ["#" * 6] + ["#....#"] * 4 + ["#" * 6]
    w = SimpleNamespace(collision=CollisionGrid.from_rows(rows))
    p = Player(20, 20)
    p.dash_toward((1, 0), 6)
    run(p, w, 0.5)
    assert p.x == pytest.approx(80 - p.w)
    assert not p.dashing


def test_attack_timing_and_queue():
    w = open_world()
    p = Player(100, 100)
    p.attack(3)  # "3x"
    assert p.attack_box() is not None
    assert p.queued_strikes == 2
    strikes_seen = {p.strike_id}
    active_frames = 0
    total = P.ATTACK_ACTIVE + P.ATTACK_RECOVERY
    for _ in range(round(3 * total / DT) + 5):
        p.update(DT, w)
        if p.attack_box() is not None:
            active_frames += 1
        strikes_seen.add(p.strike_id)
    assert strikes_seen == {1, 2, 3}
    assert not p.attacking
    # ~0.15s of active hitbox per strike (first frame counted before the loop)
    assert abs(active_frames + 1 - 3 * round(P.ATTACK_ACTIVE / DT)) <= 3


def test_attack_box_faces_direction_and_roots_player():
    w = open_world()
    p = Player(100, 100)
    p.facing = (0, -1)
    p.attack()
    x, y, bw, bh = p.attack_box()
    cx, cy = p.center
    assert (x + bw / 2, y + bh / 2) == (cx, cy - 16)
    p.update(DT, w, move=(1, 0))
    assert p.x == 100  # rooted during the active window


def test_attack_hurts_wanderer():
    e = Wanderer(0, 0, hp=2)
    assert e.hurt(1, (10, 0))
    assert not e.hurt(1)  # i-frames
    e.iframes = 0
    assert e.hurt(1)
    assert not e.alive


def test_wanderer_stays_inside_room():
    import random

    rows = ["#" * 8] + ["#......#"] * 6 + ["#" * 8]
    w = SimpleNamespace(collision=CollisionGrid.from_rows(rows))
    e = Wanderer(50, 50, rng=random.Random(1), speed=60)
    for _ in range(600):
        e.update(DT, w)
        assert 16 <= e.x and e.x + e.w <= 112 + 1e-6
        assert 16 <= e.y and e.y + e.h <= 112 + 1e-6
