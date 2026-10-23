"""The dialogue panel: a transparent scene drawn over the frozen world.

Keys: ``j`` / Enter / Space finish the typewriter reveal or advance to the next line;
with choices showing, ``j``/``k`` (or Down/Up) move and Enter/Space picks; Esc skips the
whole conversation. When it ends the dialogue's ``sets`` flags (plus the chosen reply's)
go into ``game.progress.flags`` if the game has a ``progress``, else into ``flags``.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING, Any

import pygame

from coderogue.scene import Scene
from coderogue.story.dialogue import Choice, Dialogue
from coderogue.story.flags import apply_flags
from coderogue.ui.text import get_font, render_text

if TYPE_CHECKING:
    from coderogue.app import Game

PANEL_BG = (0x0E, 0x0D, 0x12)
ACCENT = (0x50, 0xC8, 0xA0)
TEXT = (0xE6, 0xE1, 0xD6)
DIM = (0x8A, 0x86, 0x7E)
BORDER = (0x2A, 0x28, 0x33)
REVEAL_CPS = 40.0
MARGIN = 16
PADDING = 16
PANEL_HEIGHT = 156
NAME_SIZE = 18
BODY_SIZE = 16
LINE_GAP = 4

ADVANCE_KEYS = (pygame.K_j, pygame.K_RETURN, pygame.K_KP_ENTER, pygame.K_SPACE)
DOWN_KEYS = (pygame.K_j, pygame.K_DOWN)
UP_KEYS = (pygame.K_k, pygame.K_UP)
PICK_KEYS = (pygame.K_RETURN, pygame.K_KP_ENTER, pygame.K_SPACE)


def wrap_text(text: str, width: int, measure: Callable[[str], int]) -> list[str]:
    """Greedy word wrap of ``text`` to ``width`` pixels; ``measure`` returns a width."""
    out: list[str] = []
    for paragraph in text.split("\n"):
        line = ""
        for word in paragraph.split(" "):
            candidate = f"{line} {word}" if line else word
            if line and measure(candidate) > width:
                out.append(line)
                line = word
            else:
                line = candidate
        out.append(line)
    return out


class DialogueScene(Scene):
    """Shows one :class:`Dialogue`, then pops itself and calls ``on_done(choice)``."""

    transparent = True

    def __init__(
        self,
        game: Game,
        dialogue: Dialogue,
        on_done: Callable[[Choice | None], None] | None = None,
        flags: Any = None,
    ) -> None:
        super().__init__(game)
        self.dialogue = dialogue
        self.on_done = on_done
        self.flags = flags if flags is not None else set()
        self.index = 0
        self.elapsed = 0.0
        self.choosing = False
        self.cursor = 0
        self.finished = False
        self.chosen: Choice | None = None

    # ---- state ------------------------------------------------------------------------
    @property
    def line(self) -> str:
        """The current line's full text."""
        return self.dialogue.lines[self.index]

    @property
    def revealed(self) -> int:
        """How many characters of the current line are visible."""
        return min(len(self.line), int(self.elapsed * REVEAL_CPS))

    @property
    def line_complete(self) -> bool:
        """True once the whole current line is visible."""
        return self.revealed >= len(self.line)

    def target_flags(self) -> Any:
        """Where finished-dialogue flags go: ``game.progress.flags`` or ``self.flags``."""
        progress = getattr(self.game, "progress", None)
        flags = getattr(progress, "flags", None)
        return flags if flags is not None else self.flags

    def advance(self) -> None:
        """Complete the reveal, or go to the next line / the choices / the end."""
        if self.finished:
            return
        if self.choosing:
            self.choose(self.cursor)
        elif not self.line_complete:
            self.elapsed = len(self.line) / REVEAL_CPS + 1e-6
        elif self.index + 1 < len(self.dialogue.lines):
            self.index += 1
            self.elapsed = 0.0
        elif self.dialogue.choices:
            self.choosing = True
            self.cursor = 0
        else:
            self.finish(None)

    def choose(self, i: int) -> None:
        """Pick reply ``i`` and end."""
        self.finish(self.dialogue.choices[i])

    def skip(self) -> None:
        """Esc: end now (dialogue ``sets`` still apply, no reply is chosen)."""
        self.finish(None)

    def finish(self, choice: Choice | None) -> None:
        """Apply flags, pop if on top, then call ``on_done``."""
        if self.finished:
            return
        self.finished = True
        self.chosen = choice
        apply_flags(self.target_flags(), self.dialogue.flags_on_finish(choice))
        if self.game.scene is self:
            self.game.pop()
        if self.on_done is not None:
            self.on_done(choice)

    # ---- scene hooks ------------------------------------------------------------------
    def handle_event(self, event: pygame.event.Event) -> None:
        """Keyboard control (KEYDOWN only)."""
        if event.type != pygame.KEYDOWN or self.finished:
            return
        key = event.key
        if key == pygame.K_ESCAPE:
            self.skip()
        elif self.choosing:
            n = len(self.dialogue.choices)
            if key in DOWN_KEYS:
                self.cursor = (self.cursor + 1) % n
            elif key in UP_KEYS:
                self.cursor = (self.cursor - 1) % n
            elif key in PICK_KEYS:
                self.choose(self.cursor)
        elif key in ADVANCE_KEYS:
            self.advance()

    def update(self, dt: float) -> None:
        """Advance the typewriter."""
        if not self.choosing:
            self.elapsed += dt

    def draw(self, surface: pygame.Surface) -> None:
        """Bottom panel: speaker, wrapped body, choices or a continue prompt."""
        sw, sh = surface.get_size()
        n_choices = len(self.dialogue.choices) if self.choosing else 0
        height = PANEL_HEIGHT + n_choices * (BODY_SIZE + 8)
        rect = pygame.Rect(MARGIN, sh - MARGIN - height, sw - 2 * MARGIN, height)
        panel = pygame.Surface(rect.size, pygame.SRCALPHA)
        panel.fill((*PANEL_BG, 240))
        surface.blit(panel, rect.topleft)
        pygame.draw.rect(surface, BORDER, rect, 1)
        pygame.draw.line(surface, ACCENT, rect.topleft, (rect.left, rect.bottom - 1), 3)

        x, y = rect.left + PADDING + 4, rect.top + PADDING - 4
        if self.dialogue.speaker:
            surface.blit(render_text(self.dialogue.speaker, NAME_SIZE, ACCENT, True), (x, y))
            y += NAME_SIZE + 10
        font = get_font(BODY_SIZE)
        width = rect.width - 2 * PADDING - 8
        shown = self.line[: self.revealed] if not self.choosing else self.line
        for row in wrap_text(shown, width, lambda s: font.size(s)[0]):
            surface.blit(render_text(row, BODY_SIZE, TEXT), (x, y))
            y += BODY_SIZE + LINE_GAP

        if self.choosing:
            y += 6
            for i, choice in enumerate(self.dialogue.choices):
                selected = i == self.cursor
                marker = "> " if selected else "  "
                color = ACCENT if selected else TEXT
                surface.blit(render_text(marker + choice.text, BODY_SIZE, color), (x, y))
                y += BODY_SIZE + 8
            hint = "j/k choose   Enter pick"
        elif self.line_complete:
            more = self.index + 1 < len(self.dialogue.lines) or self.dialogue.choices
            hint = "j  next" if more else "j  done"
        else:
            hint = ""
        if hint:
            img = render_text(hint + "   Esc skip", 12, DIM)
            surface.blit(img, (rect.right - PADDING - img.get_width(), rect.bottom - 22))
