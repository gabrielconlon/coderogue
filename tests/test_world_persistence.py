"""Boss phase drafts, map-triggered boss dialogue, the boss seal, golem dismissal and crate
persistence (real content maps, headless)."""

from __future__ import annotations

from pathlib import Path

import pygame
import pytest

from coderogue.altar import game_puzzles
from coderogue.app import Game, resource_path, start_world
from coderogue.entities.boss import Boss
from coderogue.entities.enemies import StampGolem
from coderogue.progress import Progress
from coderogue.save.store import SaveState, SaveStore
from coderogue.story.scene import DialogueScene
from coderogue.world.scene import WorldScene

TS = 16


def _map(name: str) -> Path:
    return resource_path("content", "maps", f"{name}.tmj")


@pytest.fixture
def game(tmp_path, monkeypatch):
    monkeypatch.setenv("CODEROGUE_HOME", str(tmp_path))
    g = Game(headless=True)
    g.progress = Progress()
    yield g
    pygame.quit()


def _world(game: Game, name: str) -> WorldScene:
    world = WorldScene(game, _map(name))
    game.push(world)
    game.world = world
    return world


def _finish_dialogue(game: Game) -> DialogueScene:
    scene = game.scene
    assert isinstance(scene, DialogueScene)
    scene.skip()
    if game.scene is scene:  # a choice is waiting
        scene.choose(0)
    assert game.scene is not scene
    return scene


# ---- 1. boss drafts per phase: save files round trip ----------------------------------------
def test_phase_draft_file_name():
    assert SaveStore.spell_name("ch1-b#1", "python") == "ch1-b__1.py"
    assert SaveStore.spell_name("ch0-01", "bash") == "ch0-01.sh"


def test_phase_drafts_round_trip_through_save(tmp_path):
    store = SaveStore(tmp_path, ledger_enabled=False)
    progress = Progress()
    progress.set_draft("ch1-b#0", "python", "print('a')\n")
    progress.set_draft("ch1-b#1", "python", "print('b')\n")
    progress.set_draft("ch0-01", "python", "print('x')\n")
    store.save("slot1", SaveState(map="echo_vale", progress=progress.to_dict()))
    spells = tmp_path / "profiles" / "slot1" / "spells"
    assert {p.name for p in spells.iterdir()} == {"ch1-b__0.py", "ch1-b__1.py", "ch0-01.py"}
    loaded = store.load("slot1")
    assert loaded is not None
    back = Progress.from_dict(loaded.progress)
    assert back.draft("ch1-b#0", "python") == "print('a')\n"
    assert back.draft("ch1-b#1", "python") == "print('b')\n"
    assert back.draft("ch0-01", "python") == "print('x')\n"
    assert back.draft("ch1-b", "python") is None


# ---- 2. boss dialogue from map properties ---------------------------------------------------
def test_mire_heart_intro_plays_once(game):
    world = _world(game, "mire_heart")
    game.step()
    scene = game.scene
    assert isinstance(scene, DialogueScene) and scene.dialogue.id == "ouroboros"
    _finish_dialogue(game)
    assert game.scene is world
    world.load_map("mire_heart")
    game.step()
    assert game.scene is world


def test_intro_waits_for_the_world_to_be_on_top(game):
    world = _world(game, "hall_of_echoes")
    game.push(DialogueScene(game, world.dialogue_bank.get("pip_intro")))
    blocker = game.scene
    game.step()
    assert game.scene is blocker
    game.pop()
    game.step()
    assert isinstance(game.scene, DialogueScene)
    assert game.scene.dialogue.id == "grubble_intro"


def test_reentry_after_the_win_plays_only_unseen_lines(game):
    game.progress.flags.update({"solved:ch1-b", "entered:echo_vale"})
    world = _world(game, "hall_of_echoes")
    game.step()
    # grubble_intro is excluded by ``unless``; grubble_defeated waits for the boss to fall
    assert isinstance(game.scene, DialogueScene)
    assert game.scene.dialogue.id == "grubble_defeated"
    _finish_dialogue(game)
    world.load_map("hall_of_echoes")
    game.step()
    assert game.scene is world


@pytest.mark.parametrize(
    ("name", "pid", "expected"),
    [("hall_of_echoes", "ch1-b", "grubble_defeated"),
     ("mire_heart", "ch2-b", "ouroboros_defeated"),
     ("census_hall", "ch3-b", "archivist_defeated")],
)
def test_defeat_dialogue_plays_when_the_boss_falls(game, name, pid, expected):
    world = _world(game, name)
    game.step()
    if isinstance(game.scene, DialogueScene):
        _finish_dialogue(game)
    boss = next(e for e in world.enemies if isinstance(e, Boss))
    game.progress.flags.add(f"solved:{pid}")  # on_puzzle_solved sets it first
    boss.alive = False
    game.step()  # reap reports the death; the dialogue is queued
    game.step()
    scene = game.scene
    assert isinstance(scene, DialogueScene) and scene.dialogue.id == expected
    _finish_dialogue(game)
    game.step()
    assert game.scene is world


# ---- 3. seal before tag ---------------------------------------------------------------------
def test_boss_solve_seals_then_tags(game):
    world = _world(game, "hall_of_echoes")
    calls: list[str] = []
    saves = game.saves
    real_save, real_tag = saves.save, saves.tag_chapter

    def save(slot, state, message=None):
        calls.append("save")
        assert "solved:ch1-b" in state.progress["flags"]
        return real_save(slot, state, message)

    def tag(slot, name):
        calls.append(f"tag:{name}")
        return real_tag(slot, name)

    saves.save, saves.tag_chapter = save, tag  # type: ignore[method-assign]
    spec = game_puzzles(game)["ch1-b"]
    game.progress.mark_solved("ch1-b", "python")
    world.on_puzzle_solved(spec, None)  # type: ignore[arg-type]
    assert calls == ["save", "tag:ch1"]
    ledger = saves.ledger("slot1")
    if ledger.available:
        assert "ch1" in ledger.tags()
        assert world.message.endswith("(Sealed in the Ledger as ch1.)")
    else:
        assert world.message.endswith("(Saved.)")
    assert saves.exists("slot1")


# ---- 4. stamp golems ------------------------------------------------------------------------
def _golems(world: WorldScene) -> list[StampGolem]:
    return [e for e in world.enemies if isinstance(e, StampGolem)]


def test_golems_dismissed_when_their_puzzle_is_solved(game):
    world = _world(game, "grand_directory")
    golems = _golems(world)
    assert sorted(g.name for g in golems) == ["golem_a", "golem_b"]
    game.step()  # golems mark their tiles solid on the first step
    tiles = [t for g in golems for t in g.blocked_tiles]
    assert tiles and all(world.collision.is_solid(*t) for t in tiles)
    xp = game.progress.xp
    game.progress.mark_solved("ch3-03", "python")
    world.on_puzzle_solved(game_puzzles(game)["ch3-03"], None)  # type: ignore[arg-type]
    assert not _golems(world)
    assert all(g.dismissed and not g.alive for g in golems)
    assert not any(world.collision.is_solid(*t) for t in tiles)
    game.step()
    assert not any(world.collision.is_solid(*t) for t in tiles)
    assert game.progress.xp == xp  # not kills


def test_golems_gone_on_load_when_solved(game):
    game.progress.mark_solved("ch3-03", "python")
    world = _world(game, "grand_directory")
    assert not _golems(world)
    game.step()
    world.load_map("grand_directory")
    assert not _golems(world)


def test_golem_tiles_survive_a_collision_rebuild(game):
    world = _world(game, "grand_directory")
    game.step()
    tiles = [t for g in _golems(world) for t in g.blocked_tiles]
    world._solid_sig = None
    world._update_world_state()
    assert all(world.collision.is_solid(*t) for t in tiles)


# ---- 5. crates ------------------------------------------------------------------------------
def _crate_on_plate(world: WorldScene) -> None:
    crate = next(c for c in world.liftables if c.name == "crate_tutorial")
    plate = next(p for p in world.plates if p.name == "plate_gallery")
    world.liftables.remove(crate)
    world.player.carrying = crate
    world.player.place_center(plate.center[0] - 13, plate.center[1])
    world.player.facing = (1, 0)
    assert world.put()
    world._update_world_state()


def _assert_crate_on_plate(world: WorldScene) -> None:
    crate = next(c for c in world.liftables if c.name == "crate_tutorial")
    plate = next(p for p in world.plates if p.name == "plate_gallery")
    gate = next(d for d in world.doors if d.name == "/directory/gossip-gallery")
    assert crate.center == plate.center
    assert plate.pressed and not gate.locked


def test_crate_stays_on_plate_across_maps_and_saves(game):
    world = _world(game, "grand_directory")
    _crate_on_plate(world)
    _assert_crate_on_plate(world)
    assert world.crates["grand_directory"]["crate_tutorial"] == [9, 11]
    world.load_map("mire_heart")
    world.load_map("grand_directory")
    _assert_crate_on_plate(world)
    world.save_game()
    other = Game(headless=True)
    restored = start_world(other, _map("little_tilde_scriptorium"), new=False)
    assert restored.map_key == "grand_directory"
    _assert_crate_on_plate(restored)
    restored.load_map("mire_heart")
    restored.load_map("grand_directory")
    _assert_crate_on_plate(restored)


def test_crate_carried_off_the_map_goes_home(game):
    world = _world(game, "grand_directory")
    _crate_on_plate(world)
    crate = next(c for c in world.liftables if c.name == "crate_tutorial")
    world.liftables.remove(crate)
    world.player.carrying = crate
    world.load_map("mire_heart")
    world.load_map("grand_directory")
    home = next(c for c in world.liftables if c.name == "crate_tutorial")
    assert home.tile(TS) == (4, 19)
    gate = next(d for d in world.doors if d.name == "/directory/gossip-gallery")
    assert gate.locked
