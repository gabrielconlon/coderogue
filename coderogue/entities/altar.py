"""Altars: shards of the Terminal where coding puzzles happen."""

from __future__ import annotations

from typing import Any

import pygame

from .base import Entity

INTERACT_REACH = 4  # px the interaction zone extends beyond the altar's 16x16 box


class Altar(Entity):
    """Static, non-solid altar. The scene calls ``on_altar(altar)`` on INTERACT while the
    player overlaps :meth:`interact_box`. ``puzzle`` comes from the map object's ``puzzle``
    custom property (or its name)."""

    def __init__(
        self,
        x: float,
        y: float,
        sprite: pygame.Surface | None = None,
        name: str = "",
        properties: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(x, y, 16, 16, sprite, name=name, properties=properties)
        self.anim_time = 0.0

    @property
    def puzzle(self) -> str:
        """Puzzle id this altar opens (``puzzle`` property, falling back to the name)."""
        return str(self.properties.get("puzzle") or self.name)

    def interact_box(self) -> tuple[float, float, float, float]:
        """Area in which the player can interact."""
        r = INTERACT_REACH
        return (self.x - r, self.y - r, self.w + 2 * r, self.h + 2 * r)

    def update(self, dt: float, world: Any) -> None:
        """Gentle hover animation."""
        self.anim_time += dt
