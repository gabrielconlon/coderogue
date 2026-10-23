"""Boss lecterns: one phase per lectern, reported to the world as each phase is won."""

from types import SimpleNamespace

import pygame
import pytest

from coderogue.altar.scene import AltarScene
from coderogue.app import Game, resource_path
from coderogue.entities.altar import Altar
from coderogue.progress import Progress
from coderogue.puzzles import load_puzzle


@pytest.fixture
def game():
    g = Game(headless=True)
    yield g
    pygame.quit()


def _scene(game, world, phase, single):
    spec = load_puzzle(resource_path("content", "puzzles", "ch1", "c1_b_grubble.yaml"))
    altar = Altar(0, 0, None, name="lectern", properties={})
    return AltarScene(game, world, altar, spec, Progress(), start_phase=phase, single_phase=single)


def test_single_phase_lectern_reports_and_closes(game):
    won = []
    world = SimpleNamespace(on_boss_phase_solved=lambda spec, i: won.append(i))
    scene = _scene(game, world, 1, True)
    assert scene.phase == 1
    assert scene._on_pass(SimpleNamespace(passed=True)) is True
    assert won == [1] and scene.closing > 0 and scene.phase == 1
    assert "phase:ch1-b:1" in scene.progress.flags
    assert not scene.progress.is_solved("ch1-b")


def test_multi_phase_altar_advances_then_solves(game):
    won = []
    world = SimpleNamespace(on_boss_phase_solved=lambda spec, i: won.append(i))
    scene = _scene(game, world, None, False)
    assert scene.phase == 0
    assert scene._on_pass(SimpleNamespace(passed=True)) is False and scene.phase == 1
    assert scene._on_pass(SimpleNamespace(passed=True)) is False and scene.phase == 2
    assert scene._on_pass(SimpleNamespace(passed=True)) is True
    assert won == [0, 1, 2] and scene.progress.is_solved("ch1-b")
