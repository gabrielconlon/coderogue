"""World wiring: NPC dialogue on INTERACT, :save round-trips through the store and Ledger."""

from __future__ import annotations

import pygame
import pytest

from coderogue.app import Game, _restore_save, resource_path
from coderogue.story.scene import DialogueScene
from coderogue.world.scene import SAVE_SLOT, WorldScene

MAP = resource_path("content", "maps", "test_room.tmj")


@pytest.fixture
def game(tmp_path, monkeypatch):
    monkeypatch.setenv("CODEROGUE_HOME", str(tmp_path))
    g = Game(headless=True)
    yield g
    pygame.quit()


def test_npc_spawns_and_talks(game):
    world = WorldScene(game, MAP)
    game.push(world)
    assert [n.name for n in world.npcs] == ["Pell"]
    npc = world.npcs[0]
    world.player.place_center(*npc.center)
    world.talk_to_npc_in_reach()
    assert isinstance(game.scene, DialogueScene)
    assert game.scene.dialogue.speaker == "Pell"


def test_save_then_restore_round_trip(game):
    world = WorldScene(game, MAP)
    game.push(world)
    world.player.x, world.player.y = 123.0, 77.0
    game.progress.flags.add("met_pell")
    game.progress.xp = 40
    world.run_command("save")
    assert "first_seal" in game.progress.flags
    assert game.saves.exists(SAVE_SLOT)

    fresh = Game(headless=True)
    world2 = WorldScene(fresh, MAP)
    _restore_save(fresh, world2)
    assert fresh.progress.xp == 40 and "met_pell" in fresh.progress.flags
    assert (world2.player.x, world2.player.y) == (123.0, 77.0)


def test_ledger_command_does_not_raise(game):
    world = WorldScene(game, MAP)
    game.push(world)
    world.run_command("ledger")
    world.run_command("save")
    world.run_command("ledger")
    assert world.message
