"""Altars: shards of the Terminal where coding puzzles happen."""

from __future__ import annotations

import math
from typing import Any

import pygame

from .base import Entity

INTERACT_REACH = 4  # px the interaction zone extends beyond the altar's 16x16 box


def dim_sprite(sprite: pygame.Surface) -> pygame.Surface:
    """A desaturated, darkened copy of ``sprite`` (an altar that has not been lit yet)."""
    grey = pygame.transform.grayscale(sprite)
    shade = pygame.Surface(grey.get_size(), pygame.SRCALPHA)
    shade.fill((150, 150, 165, 255))
    grey.blit(shade, (0, 0), special_flags=pygame.BLEND_RGBA_MULT)
    return grey


class Altar(Entity):
    """Static, non-solid altar. The scene calls ``on_altar(altar)`` on INTERACT while the
    player overlaps :meth:`interact_box`. ``puzzle`` comes from the map object's ``puzzle``
    custom property (or its name).

    ``lit`` altars (puzzle solved) draw in full colour with a soft glow; unlit ones are drawn
    desaturated."""

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
        self.lit = False
        self._dim: pygame.Surface | None = None

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

    def draw(self, surface: pygame.Surface, offset: tuple[int, int]) -> None:
        """Draw lit (full colour, glowing) or unlit (desaturated)."""
        if self.sprite is None or not self.visible:
            return
        if self.lit:
            cx = round(self.x + self.w / 2) - offset[0]
            cy = round(self.y + self.h / 2) - offset[1]
            pulse = 0.5 + 0.5 * math.sin(self.anim_time * 3.0)
            radius = 11 + round(2 * pulse)
            glow = pygame.Surface((radius * 2, radius * 2), pygame.SRCALPHA)
            pygame.draw.circle(glow, (240, 200, 110, 60 + round(40 * pulse)),
                               (radius, radius), radius)
            surface.blit(glow, (cx - radius, cy - radius))
            super().draw(surface, offset)
            return
        if self._dim is None:
            self._dim = dim_sprite(self.sprite)
        lit_sprite, self.sprite = self.sprite, self._dim
        try:
            super().draw(surface, offset)
        finally:
            self.sprite = lit_sprite
