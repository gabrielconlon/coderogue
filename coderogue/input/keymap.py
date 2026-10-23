"""Action names and key bindings.

The default binding is VIM: ``h j k l`` to move, ``x`` to strike, ``w``/``b`` to dash,
``Enter``/``i`` to interact, ``Esc`` to escape and ``:`` for the command line. World
mechanics add ``v`` (lock-on), ``d`` (``dd`` cleave), ``u`` (rewind), ``y``/``p`` (``yy`` lift,
``p`` put), ``/`` and ``n`` (search), ``m`` and ``'`` (marks). With
``arrows_fallback=True`` the arrow keys and WASD are bound *as well* (WASD's ``w`` then
moves up instead of dashing, so dashes move to Shift / Ctrl in fallback mode).
"""

from __future__ import annotations

from enum import Enum, auto

import pygame


class Action(Enum):
    """Abstract game actions. Scenes react to actions, never to raw keys."""

    MOVE_LEFT = auto()
    MOVE_DOWN = auto()
    MOVE_UP = auto()
    MOVE_RIGHT = auto()
    ATTACK = auto()
    DASH_FWD = auto()
    DASH_BACK = auto()
    INTERACT = auto()
    ESCAPE = auto()
    COMMAND = auto()
    VISUAL = auto()
    UNDO = auto()
    CONFIRM = auto()
    DEBUG = auto()
    DELETE = auto()  # ``d``: the world scene turns ``dd`` into a cleave
    YANK = auto()  # ``y``: ``yy`` lifts a liftable object
    PUT = auto()  # ``p``: put the carried object down
    SEARCH = auto()  # ``/``: start a search prompt
    SEARCH_NEXT = auto()  # ``n``: next search match
    MARK = auto()  # ``m`` + letter: set a mark at a waystone
    HELP = auto()  # ``?`` or F1: toggle the controls overlay
    JUMP_MARK = auto()  # ``'`` + letter: fast-travel to a mark


MOVE_ACTIONS: dict[Action, tuple[int, int]] = {
    Action.MOVE_LEFT: (-1, 0),
    Action.MOVE_DOWN: (0, 1),
    Action.MOVE_UP: (0, -1),
    Action.MOVE_RIGHT: (1, 0),
}

VIM_KEYS: dict[int, Action] = {
    pygame.K_h: Action.MOVE_LEFT,
    pygame.K_j: Action.MOVE_DOWN,
    pygame.K_k: Action.MOVE_UP,
    pygame.K_l: Action.MOVE_RIGHT,
    pygame.K_x: Action.ATTACK,
    pygame.K_w: Action.DASH_FWD,
    pygame.K_b: Action.DASH_BACK,
    pygame.K_i: Action.INTERACT,
    pygame.K_RETURN: Action.INTERACT,
    pygame.K_KP_ENTER: Action.INTERACT,
    pygame.K_ESCAPE: Action.ESCAPE,
    pygame.K_v: Action.VISUAL,
    pygame.K_u: Action.UNDO,
    pygame.K_F3: Action.DEBUG,
    pygame.K_F1: Action.HELP,
    pygame.K_d: Action.DELETE,
    pygame.K_y: Action.YANK,
    pygame.K_p: Action.PUT,
    pygame.K_n: Action.SEARCH_NEXT,
    pygame.K_m: Action.MARK,
}

FALLBACK_KEYS: dict[int, Action] = {
    pygame.K_LEFT: Action.MOVE_LEFT,
    pygame.K_DOWN: Action.MOVE_DOWN,
    pygame.K_UP: Action.MOVE_UP,
    pygame.K_RIGHT: Action.MOVE_RIGHT,
    pygame.K_a: Action.MOVE_LEFT,
    pygame.K_s: Action.MOVE_DOWN,
    pygame.K_w: Action.MOVE_UP,
    pygame.K_d: Action.MOVE_RIGHT,
    pygame.K_SPACE: Action.ATTACK,
    pygame.K_LSHIFT: Action.DASH_FWD,
    pygame.K_RSHIFT: Action.DASH_FWD,
    pygame.K_LCTRL: Action.DASH_BACK,
    pygame.K_e: Action.INTERACT,
}

# Bindings matched on the typed character rather than the key (``:`` is Shift+; on US
# layouts but a plain key elsewhere).
VIM_CHARS: dict[str, Action] = {
    ":": Action.COMMAND,
    "?": Action.HELP,
    "/": Action.SEARCH,
    "'": Action.JUMP_MARK,
}


class Keymap:
    """Maps pygame key events to :class:`Action` values."""

    def __init__(
        self,
        keys: dict[int, Action] | None = None,
        chars: dict[str, Action] | None = None,
        arrows_fallback: bool = False,
    ) -> None:
        self.keys: dict[int, Action] = dict(VIM_KEYS if keys is None else keys)
        self.chars: dict[str, Action] = dict(VIM_CHARS if chars is None else chars)
        self.arrows_fallback = arrows_fallback
        if arrows_fallback:
            self.keys.update(FALLBACK_KEYS)

    @classmethod
    def default(cls, arrows_fallback: bool = False) -> Keymap:
        """The default VIM keymap, optionally with arrows/WASD added."""
        return cls(arrows_fallback=arrows_fallback)

    def action_for_key(self, key: int, unicode: str = "") -> Action | None:
        """Resolve a key press. Character bindings win over key bindings."""
        if unicode and unicode in self.chars:
            return self.chars[unicode]
        return self.keys.get(key)

    def action_for_event(self, event: pygame.event.Event) -> Action | None:
        """Resolve a KEYDOWN/KEYUP event to an action (None if unbound or not a key event)."""
        if event.type not in (pygame.KEYDOWN, pygame.KEYUP):
            return None
        unicode = getattr(event, "unicode", "") if event.type == pygame.KEYDOWN else ""
        return self.action_for_key(event.key, unicode)

    def keys_for(self, action: Action) -> list[int]:
        """All keys bound to ``action``."""
        return [k for k, a in self.keys.items() if a is action]
