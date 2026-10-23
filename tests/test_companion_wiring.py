"""Moth follows Wren once moth_joined is set, and the static Moth npc hides."""

import pygame
import pytest

from coderogue.app import Game, resource_path
from coderogue.world.scene import WorldScene


@pytest.fixture
def game(tmp_path, monkeypatch):
    monkeypatch.setenv("CODEROGUE_HOME", str(tmp_path))
    g = Game(headless=True)
    yield g
    pygame.quit()


def test_companion_appears_after_moth_joins(game):
    world = WorldScene(game, resource_path("content", "maps", "little_tilde.tmj"))
    game.push(world)
    assert world.companion is None
    moth = next(n for n in world.npcs if n.key == "moth")
    assert moth.visible
    game.progress.flags.add("moth_joined")
    for _ in range(120):
        game.step(1 / 60)
    assert world.companion is not None and not moth.visible
    px, py = world.player.center
    cx, cy = world.companion.center
    assert abs(px - cx) + abs(py - cy) < 60
    game.draw()  # draws with the companion in the entity list
    world.load_map("echo_vale", "spawn", show_card=False)
    assert world.companion is not None
