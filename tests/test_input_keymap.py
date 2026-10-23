import pygame

from coderogue.input.keymap import Action, Keymap


def test_vim_defaults():
    km = Keymap.default()
    assert km.action_for_key(pygame.K_h) is Action.MOVE_LEFT
    assert km.action_for_key(pygame.K_j) is Action.MOVE_DOWN
    assert km.action_for_key(pygame.K_k) is Action.MOVE_UP
    assert km.action_for_key(pygame.K_l) is Action.MOVE_RIGHT
    assert km.action_for_key(pygame.K_x) is Action.ATTACK
    assert km.action_for_key(pygame.K_w) is Action.DASH_FWD
    assert km.action_for_key(pygame.K_b) is Action.DASH_BACK
    assert km.action_for_key(pygame.K_i) is Action.INTERACT
    assert km.action_for_key(pygame.K_RETURN) is Action.INTERACT
    assert km.action_for_key(pygame.K_ESCAPE) is Action.ESCAPE
    assert km.action_for_key(pygame.K_SEMICOLON, ":") is Action.COMMAND
    assert km.action_for_key(pygame.K_LEFT) is None


def test_arrows_fallback_adds_bindings():
    km = Keymap.default(arrows_fallback=True)
    assert km.action_for_key(pygame.K_LEFT) is Action.MOVE_LEFT
    assert km.action_for_key(pygame.K_d) is Action.MOVE_RIGHT
    assert km.action_for_key(pygame.K_h) is Action.MOVE_LEFT  # VIM keys still work


def test_action_for_event():
    km = Keymap.default()
    ev = pygame.event.Event(pygame.KEYDOWN, key=pygame.K_x, unicode="x", mod=0)
    assert km.action_for_event(ev) is Action.ATTACK
    assert km.action_for_event(pygame.event.Event(pygame.MOUSEBUTTONDOWN)) is None
