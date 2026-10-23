"""Scene base class for the :class:`~coderogue.app.Game` scene stack."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pygame

if TYPE_CHECKING:
    from coderogue.app import Game


class Scene:
    """One screen of the game (world, altar editor, dialogue, pause...).

    Only the top scene of the stack receives events and updates. Drawing starts at the
    highest scene that is not ``transparent``, so a transparent modal (e.g. the altar
    editor) is drawn over the frozen scene below it.
    """

    transparent: bool = False

    def __init__(self, game: Game) -> None:
        self.game = game

    def on_enter(self) -> None:
        """Called when pushed (or when it becomes the replacement)."""

    def on_exit(self) -> None:
        """Called when popped or replaced."""

    def on_resume(self) -> None:
        """Called when the scene above it is popped and it is on top again."""

    def handle_event(self, event: pygame.event.Event) -> None:
        """Handle one pygame event (only called on the top scene)."""

    def update(self, dt: float) -> None:
        """Advance by one fixed timestep ``dt`` (seconds)."""

    def draw(self, surface: pygame.Surface) -> None:
        """Draw onto the 960x540 logical surface."""
