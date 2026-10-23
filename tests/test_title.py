"""Title screen navigation (headless)."""

from __future__ import annotations

import pygame
import pytest

from coderogue.app import Game
from coderogue.title import TitleScene


@pytest.fixture
def game(tmp_path, monkeypatch):
    monkeypatch.setenv("CODEROGUE_HOME", str(tmp_path))
    g = Game(headless=True)
    yield g
    pygame.quit()


def key(k: int, uni: str = "") -> pygame.event.Event:
    return pygame.event.Event(pygame.KEYDOWN, key=k, unicode=uni, mod=0)


def test_menu_without_save_starts_new_game(game):
    started: list[bool] = []
    title = TitleScene(game, started.append)
    game.push(title)
    assert title.menu == ["new", "settings", "quit"]
    assert title.selected == "new"
    title.handle_event(key(pygame.K_k, "k"))
    assert title.selected == "quit"
    title.handle_event(key(pygame.K_j, "j"))
    title.handle_event(key(pygame.K_RETURN, "\r"))
    assert started == [True]
    game.step()
    game.draw()


def test_continue_and_overwrite_confirmation(game):
    from coderogue.save.store import SaveState

    game.saves.ledger_enabled = False
    game.saves.save("slot1", SaveState(map="test_room"))
    started: list[bool] = []
    title = TitleScene(game, started.append)
    game.push(title)
    assert title.menu[0] == "continue"
    title.handle_event(key(pygame.K_RETURN, "\r"))
    assert started == [False]
    title.handle_event(key(pygame.K_j, "j"))
    title.handle_event(key(pygame.K_RETURN, "\r"))
    assert title.page == "confirm"
    game.draw()
    title.handle_event(key(pygame.K_n, "n"))
    assert title.page == "main" and started == [False]
    title.handle_event(key(pygame.K_j, "j"))
    title.handle_event(key(pygame.K_RETURN, "\r"))
    title.handle_event(key(pygame.K_y, "y"))
    assert started == [False, True]


def test_settings_toggles_and_quit(game):
    title = TitleScene(game, lambda new: None)
    game.push(title)
    title.pick("settings")
    assert title.menu == ["arrows", "ledger", "back"]
    before = game.arrows_fallback
    title.handle_event(key(pygame.K_RETURN, "\r"))
    assert game.arrows_fallback is not before
    ledger = game.saves.ledger_enabled
    title.handle_event(key(pygame.K_j, "j"))
    title.handle_event(key(pygame.K_RETURN, "\r"))
    assert game.saves.ledger_enabled is not ledger
    game.draw()
    title.handle_event(key(pygame.K_ESCAPE))
    assert title.page == "main"
    game.running = True
    title.pick("quit")
    assert not game.running


def test_main_pushes_title_without_flags(monkeypatch, game):
    from coderogue import app

    seen: list[object] = []
    monkeypatch.setattr(app.Game, "run", lambda self, max_frames=None: seen.append(self.scene) or 0)
    assert app.main([]) == 0
    assert isinstance(seen[0], TitleScene)
