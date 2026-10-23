"""Key bindings for the Phase 5b world mechanics."""

import pygame

from coderogue.input.keymap import Action, Keymap


def test_world_mechanic_bindings():
    km = Keymap.default()
    assert km.action_for_key(pygame.K_v) is Action.VISUAL
    assert km.action_for_key(pygame.K_u) is Action.UNDO
    assert km.action_for_key(pygame.K_d, "d") is Action.DELETE
    assert km.action_for_key(pygame.K_y, "y") is Action.YANK
    assert km.action_for_key(pygame.K_p, "p") is Action.PUT
    assert km.action_for_key(pygame.K_n, "n") is Action.SEARCH_NEXT
    assert km.action_for_key(pygame.K_m, "m") is Action.MARK
    assert km.action_for_key(pygame.K_SLASH, "/") is Action.SEARCH
    assert km.action_for_key(pygame.K_QUOTE, "'") is Action.JUMP_MARK
