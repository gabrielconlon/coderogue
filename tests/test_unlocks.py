"""Stances are learned from the story: ``world.unlocked`` derives from progress flags."""

from __future__ import annotations

import pygame
import pytest

from coderogue.app import Game, resource_path
from coderogue.entities.enemies import Wanderer
from coderogue.input.modes import Mode
from coderogue.progress import Progress
from coderogue.story.scene import DialogueScene
from coderogue.world.scene import (
    ALL_MECHANICS,
    BASE_MECHANICS,
    LOCKED_LINES,
    TOAST_TIME,
    UNLOCK_FLAGS,
    WorldScene,
)

ROOM = resource_path("content", "maps", "test_room.tmj")
DT = 1 / 60


@pytest.fixture
def game(tmp_path, monkeypatch):
    monkeypatch.setenv("CODEROGUE_HOME", str(tmp_path))
    monkeypatch.delenv("CODEROGUE_ALL_UNLOCKED", raising=False)
    g = Game(headless=True)
    yield g
    pygame.quit()


@pytest.fixture
def world(game):
    ws = WorldScene(game, ROOM)
    game.push(ws)
    ws.enemies.clear()
    return ws


def key(k: int, uni: str = "") -> pygame.event.Event:
    return pygame.event.Event(pygame.KEYDOWN, key=k, unicode=uni, mod=0)


def play_dialogue(game: Game, world: WorldScene, did: str) -> DialogueScene:
    """Push the real dialogue ``did`` and read it to the end with Enter."""
    scene = DialogueScene(game, world.dialogue_bank.get(did))
    game.push(scene)
    for _ in range(200):
        if scene.finished:
            break
        game.step()
        game.scene.handle_event(key(pygame.K_RETURN, "\r"))
    assert scene.finished and game.scene is world
    return scene


def add_bug(world: WorldScene) -> Wanderer:
    px, py = world.player.center
    bug = Wanderer(0, 0, None, hp=3, speed=0, name="bug")
    bug.turn_timer = 999
    bug.place_center(px + 20, py)
    world.enemies.append(bug)
    return bug


def test_fresh_world_has_only_the_base_mechanics(world):
    assert world.unlocked == set(BASE_MECHANICS)
    assert set(UNLOCK_FLAGS) == ALL_MECHANICS
    assert world.toast is None


def test_locked_v_flashes_and_stays_normal(game, world):
    add_bug(world)
    world.handle_event(key(pygame.K_v, "v"))
    assert world.modes.mode is Mode.NORMAL and world.locked_target is None
    assert world.message == LOCKED_LINES["visual"]


@pytest.mark.parametrize(("k", "uni", "mechanic"), [
    (pygame.K_w, "w", "dash"),
    (pygame.K_b, "b", "dash"),
    (pygame.K_3, "3", "counts"),
    (pygame.K_u, "u", "rewind"),
    (pygame.K_SLASH, "/", "search"),
    (pygame.K_n, "n", "search"),
    (pygame.K_m, "m", "marks"),
    (pygame.K_QUOTE, "'", "marks"),
])
def test_each_locked_key_has_its_line(world, k, uni, mechanic):
    world.handle_event(key(k, uni))
    assert world.message == LOCKED_LINES[mechanic]
    assert world.modes.pending_count is None
    assert world.search_input is None and world.pending_key is None
    assert not world.player.dashing


def test_locked_dd_and_yy(world):
    for ch, mechanic in (("d", "cleave"), ("y", "yank")):
        code = pygame.key.key_code(ch)
        world.handle_event(key(code, ch))
        world.handle_event(key(code, ch))
        assert world.message == LOCKED_LINES[mechanic]


def test_base_keys_are_never_locked(game, world):
    world.handle_event(key(pygame.K_x, "x"))
    assert world.player.attacking
    world.handle_event(key(pygame.K_SEMICOLON, ":"))
    assert world.modes.mode is Mode.COMMAND
    world.handle_event(key(pygame.K_ESCAPE))
    assert world.modes.mode is Mode.NORMAL


def test_sable_dialogue_unlocks_v_with_a_toast(game, world):
    assert "visual" not in world.unlocked
    play_dialogue(game, world, "sable_first")
    assert "learned_v" in game.progress.flags
    assert "visual" in world.unlocked
    assert world.toast == "New stance learned: v  lock on"
    bug = add_bug(world)
    world.handle_event(key(pygame.K_v, "v"))
    assert world.modes.mode is Mode.VISUAL and world.locked_target is bug
    for _ in range(round((TOAST_TIME + 0.1) / DT)):
        game.step()
    assert world.toast is None


def test_toasts_queue_one_at_a_time(game, world):
    play_dialogue(game, world, "crow_letter")  # counts and the Cleave together
    assert {"counts", "cleave"} <= world.unlocked
    assert world.toast == "New stance learned: 3j / 3x  counts"
    assert world.toast_queue == ["New stance learned: dd  cleave"]
    for _ in range(round((TOAST_TIME + 0.1) / DT)):
        game.step()
    assert world.toast == "New stance learned: dd  cleave" and not world.toast_queue


def test_env_override_unlocks_everything(game, world, monkeypatch):
    monkeypatch.setenv("CODEROGUE_ALL_UNLOCKED", "1")
    game.step()
    assert world.unlocked == set(BASE_MECHANICS | ALL_MECHANICS)


def test_dev_flag_unlocks_everything(game):
    game.dev_all_unlocked = True
    ws = WorldScene(game, ROOM)
    assert ALL_MECHANICS <= ws.unlocked
    assert ws.toast is None


def test_help_overlay_lists_locked_rows(game, world):
    rows = {mechanic for _, _, mechanic in world.HELP_ROWS if mechanic}
    assert rows == set(ALL_MECHANICS)
    world.show_help = True
    game.draw()  # locked rows dimmed with a padlock; must not raise


def test_save_restore_keeps_unlocks(game, world, tmp_path):
    play_dialogue(game, world, "pip_intro")
    assert "dash" in world.unlocked
    state = world.save_state()
    other = Game(headless=True)
    restored = WorldScene(other, ROOM)
    assert "dash" not in restored.unlocked
    other.progress = Progress.from_dict(state.progress)
    restored.restore_state(state)
    assert restored.unlocked == world.unlocked
    assert restored.toast is None  # a restored save does not re-announce


def test_old_saves_that_read_the_letter_know_the_cleave():
    progress = Progress.from_dict({"flags": ["read_crow_letter", "learned_counts"]})
    assert "learned_dd" in progress.flags
