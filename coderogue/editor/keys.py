"""Translate pygame events into the key strings :class:`~coderogue.editor.vim.VimEditor` expects.

Focus rule for the game integrator:

* While the editor has focus call ``pygame.key.start_text_input()``; call
  ``pygame.key.stop_text_input()`` when it loses focus. TEXTINPUT events carry the typed
  characters in INSERT / COMMAND / SEARCH (so shifted symbols and keyboard layouts work).
* In NORMAL / VISUAL, printable keys come from ``KEYDOWN.unicode`` instead, and the TEXTINPUT
  that SDL sends right after that KEYDOWN must be swallowed (otherwise pressing ``i`` would
  switch to INSERT *and* insert an ``i``). :class:`KeyTranslator` does that bookkeeping; the
  stateless :func:`translate_event` does not.
* Do not use ``pygame.key.set_repeat``: it would repeat operators and mode switches. Use
  :class:`KeyRepeater` for held motion keys in NORMAL mode instead.
"""

from __future__ import annotations

import pygame

from coderogue.editor.vim import Mode

SPECIAL_KEYS: dict[int, str] = {
    pygame.K_ESCAPE: "<Esc>",
    pygame.K_RETURN: "<CR>",
    pygame.K_KP_ENTER: "<CR>",
    pygame.K_BACKSPACE: "<BS>",
    pygame.K_TAB: "<Tab>",
    pygame.K_DELETE: "<Del>",
}

ARROW_KEYS: dict[int, str] = {
    pygame.K_LEFT: "<Left>",
    pygame.K_RIGHT: "<Right>",
    pygame.K_UP: "<Up>",
    pygame.K_DOWN: "<Down>",
}

TEXT_MODES = (Mode.INSERT, Mode.COMMAND, Mode.SEARCH)

#: Keys that auto-repeat when held in NORMAL mode.
REPEATABLE = frozenset("hjklwbe") | frozenset(ARROW_KEYS.values())


def translate_event(event: pygame.event.Event, mode: Mode = Mode.NORMAL) -> str | None:
    """Map a KEYDOWN or TEXTINPUT event to a key string for ``mode``; None to ignore it.

    Stateless: in NORMAL/VISUAL the caller must drop the TEXTINPUT echo of a consumed KEYDOWN
    (see :class:`KeyTranslator`, which does it for you).
    """
    if event.type == pygame.KEYDOWN:
        if event.key in SPECIAL_KEYS:
            return SPECIAL_KEYS[event.key]
        if event.key in ARROW_KEYS:
            return ARROW_KEYS[event.key]
        if event.mod & pygame.KMOD_CTRL:
            if event.key == pygame.K_r:
                return "<C-r>"
            if event.key == pygame.K_LEFTBRACKET:
                return "<Esc>"  # Ctrl-[ is Escape in Vim
            return None
        if mode in TEXT_MODES:
            return None  # the matching TEXTINPUT event carries the character
        char = getattr(event, "unicode", "")
        return char if len(char) == 1 and char.isprintable() else None
    if event.type == pygame.TEXTINPUT:
        if mode not in TEXT_MODES:
            return None
        text = event.text
        return text if len(text) == 1 and text.isprintable() else None
    return None


class KeyTranslator:
    """Stateful wrapper around :func:`translate_event` that swallows TEXTINPUT echoes.

    ``translate`` may return several keys for one TEXTINPUT (IME or paste), hence a list.
    """

    def __init__(self) -> None:
        self._swallow: str | None = None

    def translate(self, event: pygame.event.Event, mode: Mode) -> list[str]:
        """Return the key strings to feed for ``event`` in ``mode`` (possibly empty)."""
        if event.type == pygame.KEYDOWN:
            self._swallow = None
            key = translate_event(event, mode)
            if key is not None and len(key) == 1 and mode not in TEXT_MODES:
                self._swallow = key
            return [key] if key is not None else []
        if event.type == pygame.TEXTINPUT:
            text = event.text
            if self._swallow is not None and text == self._swallow:
                self._swallow = None
                return []
            self._swallow = None
            if mode not in TEXT_MODES:
                return []
            return [ch for ch in text if ch.isprintable()]
        return []


class KeyRepeater:
    """Auto-repeat for held motion keys in NORMAL mode (350 ms delay, then every 40 ms).

    Call :meth:`press` on KEYDOWN with the pygame keycode and the translated key, :meth:`release`
    on KEYUP, and :meth:`update` once per tick; feed the keys it returns to the editor.
    """

    def __init__(self, delay: float = 0.350, interval: float = 0.040) -> None:
        self.delay = delay
        self.interval = interval
        self._code: int | None = None
        self._key = ""
        self._timer = 0.0

    @property
    def held(self) -> str | None:
        """The key string currently being repeated, if any."""
        return self._key if self._code is not None else None

    def press(self, code: int, key: str | None, mode: Mode = Mode.NORMAL) -> None:
        """Start tracking ``key`` if it is a repeatable motion in NORMAL mode, else stop."""
        if key in REPEATABLE and mode is Mode.NORMAL:
            self._code, self._key, self._timer = code, key, -self.delay
        else:
            self.reset()

    def release(self, code: int) -> None:
        """Stop repeating if ``code`` is the held key."""
        if code == self._code:
            self.reset()

    def reset(self) -> None:
        """Stop repeating (call on focus loss or mode change)."""
        self._code, self._key, self._timer = None, "", 0.0

    def update(self, dt: float, mode: Mode = Mode.NORMAL) -> list[str]:
        """Advance by ``dt`` seconds; return the repeated keys due this tick."""
        if self._code is None:
            return []
        if mode is not Mode.NORMAL:
            self.reset()
            return []
        self._timer += dt
        out: list[str] = []
        while self._timer >= 0:
            out.append(self._key)
            self._timer -= self.interval
        return out
