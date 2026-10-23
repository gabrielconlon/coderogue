"""Title screen: Continue / New Game / Settings / Quit, navigated with ``j``/``k`` and Enter.

``on_start(new)`` is called to begin play (``new=True`` for a fresh game); the caller
replaces this scene with the world. New Game asks "Overwrite the Ledger? y/n" when a save
already exists.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING

import pygame

from coderogue.scene import Scene
from coderogue.ui import theme
from coderogue.ui.text import draw_text, render_text

if TYPE_CHECKING:
    from coderogue.app import Game

SAVE_SLOT = "slot1"
BLINK = 0.5  # cursor blink half-period (s)
DOWN_KEYS = (pygame.K_j, pygame.K_DOWN)
UP_KEYS = (pygame.K_k, pygame.K_UP)
PICK_KEYS = (pygame.K_RETURN, pygame.K_KP_ENTER, pygame.K_SPACE, pygame.K_l)


class TitleScene(Scene):
    """The first screen. ``menu`` lists item keys for the current page."""

    def __init__(self, game: Game, on_start: Callable[[bool], None]) -> None:
        super().__init__(game)
        self.on_start = on_start
        self.page = "main"  # "main" | "settings" | "confirm"
        self.index = 0
        self.time = 0.0
        self.message = ""
        self.message_time = 0.0

    # ---- state ------------------------------------------------------------------------
    @property
    def has_save(self) -> bool:
        """True if slot1 exists."""
        saves = getattr(self.game, "saves", None)
        try:
            return bool(saves is not None and saves.exists(SAVE_SLOT))
        except (OSError, ValueError):
            return False

    @property
    def menu(self) -> list[str]:
        """Item keys on the current page."""
        if self.page == "settings":
            return ["arrows", "ledger", "back"]
        if self.page == "confirm":
            return []
        items = ["continue"] if self.has_save else []
        return [*items, "new", "settings", "quit"]

    @property
    def selected(self) -> str:
        """Key of the highlighted item ("" on the confirm page)."""
        items = self.menu
        return items[self.index % len(items)] if items else ""

    def label(self, key: str) -> str:
        """Display text for a menu key."""
        if key == "arrows":
            on = bool(getattr(self.game, "arrows_fallback", False))
            return f"Arrow keys + WASD: {'on' if on else 'off'}"
        if key == "ledger":
            saves = getattr(self.game, "saves", None)
            on = bool(getattr(saves, "ledger_enabled", False))
            return f"Ledger (git saves): {'on' if on else 'off'}"
        return {
            "continue": "Continue",
            "new": "New Game",
            "settings": "Settings",
            "quit": "Quit",
            "back": "Back",
        }.get(key, key)

    def flash(self, text: str, seconds: float = 2.5) -> None:
        """Show a short note under the menu."""
        self.message = text
        self.message_time = seconds

    # ---- input ------------------------------------------------------------------------
    def handle_event(self, event: pygame.event.Event) -> None:
        """j/k move, Enter picks, Esc backs out; y/n answer the overwrite question."""
        if event.type != pygame.KEYDOWN:
            return
        if self.page == "confirm":
            if event.key == pygame.K_y:
                self.page = "main"
                self.on_start(True)
            elif event.key in (pygame.K_n, pygame.K_ESCAPE):
                self.page = "main"
                self.index = 0
            return
        if event.key in DOWN_KEYS:
            self.index = (self.index + 1) % len(self.menu)
        elif event.key in UP_KEYS:
            self.index = (self.index - 1) % len(self.menu)
        elif event.key in PICK_KEYS:
            self.pick(self.selected)
        elif event.key == pygame.K_ESCAPE and self.page == "settings":
            self.page, self.index = "main", 0

    def pick(self, key: str) -> None:
        """Activate a menu item by key."""
        if key == "continue":
            self.on_start(False)
        elif key == "new":
            if self.has_save:
                self.page = "confirm"
            else:
                self.on_start(True)
        elif key == "settings":
            self.page, self.index = "settings", 0
        elif key == "quit":
            self.game.quit()
        elif key == "arrows":
            self.game.arrows_fallback = not bool(getattr(self.game, "arrows_fallback", False))
        elif key == "ledger":
            saves = getattr(self.game, "saves", None)
            if saves is not None and hasattr(saves, "ledger_enabled"):
                saves.ledger_enabled = not saves.ledger_enabled
            else:
                self.flash("The Ledger cannot be configured here.")
        elif key == "back":
            self.page, self.index = "main", 0

    # ---- loop -------------------------------------------------------------------------
    def update(self, dt: float) -> None:
        """Advance the cursor blink and message timer."""
        self.time += dt
        self.message_time = max(0.0, self.message_time - dt)

    def draw(self, surface: pygame.Surface) -> None:
        """Title, subtitle, menu with a blinking block cursor."""
        surface.fill(theme.PANEL)
        sw, sh = surface.get_size()
        title = render_text("CodeRogue", 72, theme.ACCENT, bold=True)
        surface.blit(title, ((sw - title.get_width()) // 2, sh // 6))
        sub = render_text("The Source remembers what you write.", 18, theme.MUTED)
        surface.blit(sub, ((sw - sub.get_width()) // 2, sh // 6 + title.get_height() + 6))
        y = sh // 2
        if self.page == "confirm":
            q = "Overwrite the Ledger? y/n"
            w = render_text(q, 22, theme.WARN).get_width()
            draw_text(surface, q, ((sw - w) // 2, y), size=22, color=theme.WARN)
        else:
            x = sw // 2 - 140
            cursor_on = int(self.time / BLINK) % 2 == 0
            for key in self.menu:
                selected = key == self.selected
                if selected and cursor_on:
                    surface.fill(theme.ACCENT, (x - 24, y + 2, 12, 22))
                color = theme.TEXT if selected else theme.MUTED
                draw_text(surface, self.label(key), (x, y), size=22, color=color,
                          bold=selected)
                y += 34
        hint = "j / k: move    Enter: choose" + ("    Esc: back" if self.page != "main" else "")
        w = render_text(hint, 14, theme.DIM).get_width()
        draw_text(surface, hint, ((sw - w) // 2, sh - 40), size=14, color=theme.DIM)
        if self.message_time > 0:
            w = render_text(self.message, 16).get_width()
            draw_text(surface, self.message, ((sw - w) // 2, sh - 70), size=16,
                      color=theme.WARN)
