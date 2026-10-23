"""Waystones: signposts where the hero seals the Ledger, rests and sets marks.

``waystone`` map objects default to the Tiny Town signpost (tile 83 on the Tiny Town sheet;
set ``tile`` and ``sheet: "dungeon"`` to override). INTERACT records the waystone as the
respawn point (``world.last_waystone``) and opens :class:`WaystoneMenu`.
"""

from __future__ import annotations

import math
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

import pygame

from coderogue.scene import Scene
from coderogue.ui import theme
from coderogue.ui.panels import draw_panel
from coderogue.ui.text import draw_text, render_text

from .base import Entity

if TYPE_CHECKING:
    from coderogue.app import Game

WAYSTONE_TILE = 83  # Tiny Town signpost
INTERACT_REACH = 6

MENU_ITEMS: tuple[tuple[str, str], ...] = (
    ("seal", "Set a seal (:save)"),
    ("ledger", "Read the Ledger (:ledger)"),
    ("rest", "Rest (refill hearts and u charges)"),
    ("leave", "Leave"),
)


class Waystone(Entity):
    """A respawn point / save spot. Glows softly once visited."""

    def __init__(
        self,
        x: float,
        y: float,
        sprite: pygame.Surface | None = None,
        name: str = "",
        properties: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(x, y, 16, 16, sprite, name=name, properties=properties)
        self.visited = False
        self.anim_time = 0.0

    def interact_box(self) -> tuple[float, float, float, float]:
        """Area in which the hero can use the waystone."""
        r = INTERACT_REACH
        return (self.x - r, self.y - r, self.w + 2 * r, self.h + 2 * r)

    @property
    def stand_point(self) -> tuple[float, float]:
        """Where the hero appears when respawning or fast-travelling here (just below)."""
        cx, cy = self.center
        return (cx, cy + 14)

    def update(self, dt: float, world: Any) -> None:
        """Advance the glow."""
        self.anim_time += dt

    def draw(self, surface: pygame.Surface, offset: tuple[int, int]) -> None:
        """Draw the signpost, with a glow when visited."""
        if self.visited:
            cx = round(self.x + self.w / 2) - offset[0]
            cy = round(self.y + self.h / 2) - offset[1]
            pulse = 0.5 + 0.5 * math.sin(self.anim_time * 2.0)
            radius = 10
            glow = pygame.Surface((radius * 2, radius * 2), pygame.SRCALPHA)
            pygame.draw.circle(glow, (110, 220, 200, 40 + round(30 * pulse)),
                               (radius, radius), radius)
            surface.blit(glow, (cx - radius, cy - radius))
        super().draw(surface, offset)


class WaystoneMenu(Scene):
    """Small modal panel over the world. ``j``/``k`` move, Enter picks, Esc leaves.

    ``world`` must provide ``save_game()``, ``show_ledger()`` and ``rest_at_waystone()``.
    """

    transparent = True

    def __init__(self, game: Game, world: Any, waystone: Waystone) -> None:
        super().__init__(game)
        self.world = world
        self.waystone = waystone
        self.index = 0
        self.time = 0.0

    @property
    def choice(self) -> str:
        """Key of the highlighted item."""
        return MENU_ITEMS[self.index][0]

    def handle_event(self, event: pygame.event.Event) -> None:
        """Menu navigation."""
        if event.type != pygame.KEYDOWN:
            return
        if event.key in (pygame.K_j, pygame.K_DOWN):
            self.index = (self.index + 1) % len(MENU_ITEMS)
        elif event.key in (pygame.K_k, pygame.K_UP):
            self.index = (self.index - 1) % len(MENU_ITEMS)
        elif event.key in (pygame.K_RETURN, pygame.K_KP_ENTER, pygame.K_i, pygame.K_SPACE):
            self.pick(self.choice)
        elif event.key in (pygame.K_ESCAPE, pygame.K_q):
            self.close()

    def pick(self, key: str) -> None:
        """Run a menu entry (by key) and close the menu."""
        actions: dict[str, Callable[[], Any]] = {
            "seal": self.world.save_game,
            "ledger": self.world.show_ledger,
            "rest": self.world.rest_at_waystone,
        }
        self.close()
        action = actions.get(key)
        if action is not None:
            action()

    def close(self) -> None:
        """Pop the menu if it is on top."""
        if self.game.scene is self:
            self.game.pop()

    def update(self, dt: float) -> None:
        """Advance the cursor blink."""
        self.time += dt

    def draw(self, surface: pygame.Surface) -> None:
        """Draw the panel in the centre of the screen."""
        w, h = 420, 40 + 30 * len(MENU_ITEMS)
        sw, sh = surface.get_size()
        rect = pygame.Rect((sw - w) // 2, (sh - h) // 2, w, h)
        draw_panel(surface, rect, (*theme.PANEL, 235), theme.ACCENT, 2)
        title = self.waystone.name or "Waystone"
        draw_text(surface, title, (rect.x + 16, rect.y + 10), size=16, color=theme.GOLD,
                  bold=True)
        for i, (_, label) in enumerate(MENU_ITEMS):
            y = rect.y + 40 + i * 30
            selected = i == self.index
            color = theme.TEXT if selected else theme.MUTED
            if selected and int(self.time * 2) % 2 == 0:
                block = render_text(" ", 16, theme.TEXT)
                surface.fill(theme.ACCENT, (rect.x + 16, y, block.get_width(), 20))
            draw_text(surface, label, (rect.x + 40, y), size=16, color=color)
