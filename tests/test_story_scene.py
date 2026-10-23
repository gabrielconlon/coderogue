"""DialogueScene with simulated key events, TutorialHint fading, Npc reach."""

from types import SimpleNamespace

import pygame
import pytest

from coderogue.app import Game
from coderogue.entities.npc import Npc
from coderogue.scene import Scene
from coderogue.story.dialogue import Choice, Dialogue
from coderogue.story.scene import DialogueScene, wrap_text
from coderogue.story.tutorial import TutorialHint, split_keys


@pytest.fixture
def game():
    g = Game(headless=True)
    g.push(Scene(g))
    yield g
    pygame.quit()


def key(k):
    return pygame.event.Event(pygame.KEYDOWN, key=k, unicode="", mod=0)


DLG = Dialogue("d", "Pell", ("Hello, Wren.", "Fetch the ink."), sets=("met",), once=True)


def test_advance_through_lines_and_set_flags(game):
    flags: set[str] = set()
    done = []
    scene = DialogueScene(game, DLG, on_done=done.append, flags=flags)
    game.push(scene)
    assert scene.revealed == 0
    game.step(0.1)
    assert 0 < scene.revealed < len(DLG.lines[0])
    scene.handle_event(key(pygame.K_j))  # completes the reveal
    assert scene.line_complete and scene.index == 0
    scene.handle_event(key(pygame.K_RETURN))
    assert scene.index == 1 and scene.revealed == 0
    scene.handle_event(key(pygame.K_SPACE))
    scene.handle_event(key(pygame.K_j))
    assert scene.finished and done == [None]
    assert flags == {"met", "seen:d"}
    assert game.scene is not scene
    surf = pygame.Surface((960, 540))
    scene.draw(surf)  # drawing after finishing is harmless


def test_choices_with_jk(game):
    d = Dialogue("c", "Moth", ("Take me along?",),
                 choices=(Choice("Fine."), Choice("You're a moth.", ("rude",))))
    game.progress = SimpleNamespace(flags=set())
    scene = DialogueScene(game, d)
    game.push(scene)
    scene.handle_event(key(pygame.K_j))
    scene.handle_event(key(pygame.K_j))
    assert scene.choosing
    surf = pygame.Surface((960, 540))
    scene.draw(surf)
    scene.handle_event(key(pygame.K_j))
    assert scene.cursor == 1
    scene.handle_event(key(pygame.K_k))
    scene.handle_event(key(pygame.K_k))
    assert scene.cursor == 1  # wraps
    scene.handle_event(key(pygame.K_RETURN))
    assert scene.chosen == d.choices[1]
    assert game.progress.flags == {"rude"}


def test_escape_skips(game):
    flags: set[str] = set()
    scene = DialogueScene(game, DLG, flags=flags)
    game.push(scene)
    surf = pygame.Surface((960, 540))
    game.step(0.05)
    scene.draw(surf)
    scene.handle_event(key(pygame.K_ESCAPE))
    assert scene.finished and "met" in flags
    assert len(game.scenes) == 1
    assert DialogueScene.transparent


def test_wrap_text():
    rows = wrap_text("aa bb cc dd", 5, len)
    assert rows == ["aa bb", "cc dd"]
    assert wrap_text("one\ntwo", 100, len) == ["one", "two"]


def test_tutorial_hint_fades_after_dismiss():
    pygame.font.init()
    hint = TutorialHint("Hold `h j k l` to walk")
    assert split_keys(hint.text) == [("Hold ", False), ("h j k l", True), (" to walk", False)]
    surf = pygame.Surface((960, 540))
    for _ in range(60):
        hint.update(1 / 60)
    assert hint.alpha == 255
    hint.draw(surf)
    hint.dismiss()
    for _ in range(60):
        hint.update(1 / 60)
    assert hint.done
    hint.draw(surf)


def test_tutorial_timeout():
    hint = TutorialHint("x", timeout=0.5)
    for _ in range(120):
        hint.update(1 / 60)
    assert hint.done


def test_npc_key_and_reach():
    npc = Npc(32, 32, None, name="Pell")
    assert npc.key == "pell"
    assert Npc(0, 0, name="Shelf", properties={"dialogue": "ink_shelf"}).key == "ink_shelf"
    assert Npc(0, 0, name="X", dialogue_npc_key="Cole").key == "cole"
    x, y, w, h = npc.interact_box()
    assert x < 32 and w > 16
