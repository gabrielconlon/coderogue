"""Moth, the companion: sprite sheet, following, flipping and animation."""

from __future__ import annotations

import math

import pygame
import pytest

from coderogue.app import resource_path
from coderogue.entities import sprites
from coderogue.entities.companion import ANIM_FPS, Companion
from coderogue.entities.player import Player
from coderogue.world.collision import CollisionGrid

DT = 1 / 60


class _World:
    def __init__(self) -> None:
        self.collision = CollisionGrid(60, 20, 16, [False] * (60 * 20))


@pytest.fixture(autouse=True)
def _pygame() -> None:
    pygame.init()


def _walk(player: Player, moth: Companion, move: tuple[int, int], seconds: float) -> None:
    world = _World()
    for _ in range(round(seconds / DT)):
        player.update(DT, world, move=move)
        moth.update(DT, player)


def test_moth_sheet_has_two_transparent_frames() -> None:
    path = resource_path("assets", "sprites", "moth.png")
    assert path.exists()
    img = pygame.image.load(str(path))
    assert img.get_size() == (32, 16)
    frames = sprites.load_sheet(path, 16)
    assert len(frames) == 2
    for frame in frames:
        assert frame.get_size() == (16, 16)
        assert frame.get_at((0, 0)).a == 0 and frame.get_at((15, 15)).a == 0
        assert any(frame.get_at((x, y)) == (28, 24, 34, 255)
                   for x in range(16) for y in range(16))
    assert pygame.image.tobytes(frames[0], "RGBA") != pygame.image.tobytes(frames[1], "RGBA")


def test_sprite_generator_is_up_to_date() -> None:
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "gen_sprites", resource_path("tools", "gen_sprites.py")
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert module.main(["--check"]) == 0


def test_companion_follows_behind_the_player() -> None:
    player = Player(100, 100)
    moth = Companion.moth()
    assert moth.solid is False
    _walk(player, moth, (1, 0), 2.0)
    px, py = player.center
    mx, my = moth.center
    assert math.hypot(px - mx, py - my) <= 30
    assert mx < px  # walking right, the moth trails on the left
    assert moth.bottom > player.bottom  # sorts (draws) above the hero


def test_companion_flips_with_direction() -> None:
    player = Player(300, 100)
    moth = Companion.moth()
    _walk(player, moth, (1, 0), 1.0)
    assert moth.flip_x is True  # sprite faces left; flipped while flying right
    _walk(player, moth, (-1, 0), 1.0)
    assert moth.flip_x is False
    assert moth.center[0] > player.center[0]


def test_companion_animates_and_bobs() -> None:
    player = Player(100, 100)
    moth = Companion.moth()
    seen_frames, seen_bob = set(), set()
    for _ in range(round(1.0 / DT)):
        moth.update(DT, player)
        seen_frames.add(moth.frame)
        seen_bob.add(moth.bob)
    assert seen_frames == {0, 1}
    assert len(seen_bob) > 1
    moth.anim_time = 0.0
    moth.update(0.5 / ANIM_FPS, player)
    assert moth.frame == 0
    moth.update(1.0 / ANIM_FPS, player)
    assert moth.frame == 1


def test_companion_snaps_after_a_teleport_and_draws() -> None:
    player = Player(100, 100)
    moth = Companion.moth()
    moth.update(DT, player)
    player.x, player.y = 600, 200
    moth.update(DT, player)
    assert math.hypot(player.center[0] - moth.center[0], player.center[1] - moth.center[1]) < 40
    moth.reset()
    moth.update(DT, player)
    target = pygame.Surface((64, 64), pygame.SRCALPHA)
    moth.draw(target, (int(player.x) - 32, int(player.y) - 32))
    assert any(target.get_at((x, y)).a for x in range(64) for y in range(64))
