"""Headless tests for the altar scene, driven through the real key-translation path."""

from pathlib import Path

import pygame
import pytest

from coderogue.altar import AltarScene, game_puzzles
from coderogue.app import Game
from coderogue.editor.vim import Mode
from coderogue.languages import available
from coderogue.world.scene import WorldScene

ROOT = Path(__file__).resolve().parent.parent
TEST_ROOM = ROOT / "content" / "maps" / "test_room.tmj"
SOLUTION = 'print("Hello, Tilde.")'


@pytest.fixture
def game():
    g = Game(headless=True)
    yield g
    pygame.quit()


@pytest.fixture
def world(game):
    ws = WorldScene(game, TEST_ROOM)
    game.push(ws)
    return ws


def keydown(code: int, uni: str = "", mod: int = 0) -> pygame.event.Event:
    return pygame.event.Event(pygame.KEYDOWN, key=code, unicode=uni, mod=mod)


def send(game: Game, *events: pygame.event.Event) -> None:
    """Deliver events the way Game.run does: always to the current top scene."""
    for event in events:
        if game.scene is not None:
            game.scene.handle_event(event)


def press(game: Game, code: int) -> None:
    send(game, keydown(code))


def type_text(game: Game, text: str) -> None:
    """Each character as SDL sends it: a KEYDOWN (with unicode) then its TEXTINPUT.

    ``\\n`` is the Enter key.
    """
    for ch in text:
        if ch == "\n":
            press(game, pygame.K_RETURN)
            continue
        code = ord(ch.lower()) if ch.isascii() else 0
        send(game, keydown(code, ch), pygame.event.Event(pygame.TEXTINPUT, text=ch))


def command(game: Game, cmd: str) -> None:
    """Type ``:cmd<CR>`` from NORMAL mode."""
    type_text(game, ":" + cmd)
    press(game, pygame.K_RETURN)


def open_altar(game: Game, world: WorldScene) -> AltarScene:
    altar = world.altars[0]
    world.player.place_center(*altar.center)
    press(game, pygame.K_RETURN)  # INTERACT
    scene = game.scene
    assert isinstance(scene, AltarScene)
    return scene


def replace_buffer(game: Game, code: str) -> None:
    """Delete everything (ggdG), then type ``code`` in INSERT and return to NORMAL."""
    type_text(game, "ggdG")
    type_text(game, "i" + code)
    press(game, pygame.K_ESCAPE)


def test_interact_opens_altar_for_aliased_puzzle(game, world):
    scene = open_altar(game, world)
    assert scene.spec.id == "ch0-01"  # the map says P-01 (curriculum id)
    assert game.scenes == [world, scene] and scene.transparent
    assert scene.language in scene.usable
    assert "___" in scene.editor.text  # starter
    assert game.puzzles and "ch0-01" in game.puzzles


def test_type_solution_and_cast(game, world):
    scene = open_altar(game, world)
    replace_buffer(game, SOLUTION)
    assert scene.editor.text == SOLUTION
    assert scene.editor.mode is Mode.NORMAL
    command(game, "w")
    assert scene.result is not None and scene.result.passed
    assert game.progress.is_solved("ch0-01", "python")
    assert game.progress.xp == game.puzzles["ch0-01"].reward.xp
    assert world.altars[0].lit
    assert world.message_time > 0  # the world_effect flash
    assert scene.closing is not None and game.scene is scene
    for _ in range(int(2.5 * 60)):
        game.step()
    assert game.scene is world
    # Reopening a lit altar shows the solved state with the player's spell.
    again = open_altar(game, world)
    assert again.solved_view and again.editor.text == SOLUTION


def test_any_key_closes_after_pass(game, world):
    open_altar(game, world)
    replace_buffer(game, SOLUTION)
    command(game, "wq")
    assert game.scene is world


def test_failing_cast_shows_diff(game, world):
    scene = open_altar(game, world)
    replace_buffer(game, 'print("Hello, tilde")')
    command(game, "w")
    res = scene.result
    assert res is not None and not res.passed
    failure = res.first_failure
    assert failure is not None and failure.kind == "stdout"
    assert failure.diff is not None and failure.diff.first_diff_line == 1
    assert scene.pane == "result" and not game.progress.is_solved("ch0-01")
    scene.draw(game.surface)  # diff panel renders


def test_error_cast_sets_error_lines_and_raw_toggle(game, world):
    scene = open_altar(game, world)
    replace_buffer(game, 'x = 1\nprnt("Hello, Tilde.")')
    command(game, "w")
    res = scene.result
    assert res is not None and not res.passed and res.raw_stderr
    assert scene.view.error_lines == {res.error_line - 1} == {1}
    assert not scene.show_raw
    type_text(game, "r")
    assert scene.show_raw
    scene.draw(game.surface)
    type_text(game, "r")
    assert not scene.show_raw


def test_blank_cast_marks_blank_line(game, world):
    scene = open_altar(game, world)
    command(game, "w")
    res = scene.result
    assert res is not None and res.blank_detected
    assert scene.view.error_lines == {res.blank_line - 1}


def test_hint_ladder_cycles_and_unlocks_skip(game, world):
    scene = open_altar(game, world)
    hints = scene.variant().hints
    assert not scene.can_skip
    command(game, "skip")
    assert "ch0-01" not in game.progress.skipped
    seen = []
    for _ in range(4):
        type_text(game, "?")
        seen.append(scene.hint_shown)
        scene.draw(game.surface)
    assert seen == [1, 2, 3, 1]
    assert scene.editor.mode is Mode.NORMAL and "?" not in scene.editor.text
    assert game.progress.hint_rung("ch0-01", scene.language) == 3
    assert game.progress.hints_used["ch0-01"] == 3
    assert hints[0]
    command(game, "hint")
    assert scene.hint_shown == 2
    command(game, "skip")
    assert "ch0-01" in game.progress.skipped
    assert scene.editor.text == scene.variant().solution.rstrip("\n")
    assert scene.pane == "skip"
    scene.draw(game.surface)


def test_hint_rung_remembered_across_visits(game, world):
    scene = open_altar(game, world)
    type_text(game, "??")
    command(game, "q")
    scene = open_altar(game, world)
    type_text(game, "?")
    assert scene.hint_shown == 2


@pytest.mark.skipif("bash" not in available(), reason="bash not installed")
def test_lang_switch_keeps_separate_drafts(game, world):
    scene = open_altar(game, world)
    type_text(game, "x")  # edit the python draft (delete '#')
    py_text = scene.editor.text
    command(game, "lang bash")
    assert scene.language == "bash"
    assert scene.editor.text == scene.variant().starter.rstrip("\n")
    replace_buffer(game, 'echo "Hello, Tilde."')
    command(game, "w")
    assert game.progress.is_solved("ch0-01", "bash")
    scene.closing = None  # keep the scene open for the rest of the test
    command(game, "lang python")
    assert scene.language == "python" and scene.editor.text == py_text
    press(game, pygame.K_TAB)
    assert scene.language == "bash"
    command(game, "lang cobol")
    assert scene.language == "bash" and "Unknown" in scene.editor.last_message


def test_q_pops_and_keeps_draft(game, world):
    scene = open_altar(game, world)
    type_text(game, "dd")
    draft = scene.editor.text
    command(game, "q")
    assert game.scene is world
    assert game.progress.draft("ch0-01", scene.language) == draft
    again = open_altar(game, world)
    assert again.editor.text == draft


def test_help_overlay(game, world):
    scene = open_altar(game, world)
    command(game, "help")
    assert scene.show_help
    scene.draw(game.surface)
    type_text(game, "i")  # closes the overlay without entering INSERT
    assert not scene.show_help and scene.editor.mode is Mode.NORMAL
    command(game, "nonsense")
    assert "E492" in scene.editor.last_message


def test_headless_frames_with_altar_open(game, world):
    scene = open_altar(game, world)
    replace_buffer(game, 'print("nope")')
    command(game, "w")
    assert game.run(max_frames=120) == 0
    assert game.scene is scene and game.frame == 120


def test_lit_altar_synced_from_progress(game):
    game.progress.mark_solved("ch0-01", "python")
    ws = WorldScene(game, TEST_ROOM)
    assert ws.altars[0].lit
    assert "ch0-01" in game_puzzles(game)
