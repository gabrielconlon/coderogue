"""Liftable objects (``yy`` to lift, ``p`` to put) and the pressure plates they weigh down.

``liftable`` map objects (a crate by default, Tiny Dungeon tile 63) occupy one tile and block
movement while on the ground. ``plate`` objects are pressed while a liftable rests on them;
a door whose ``plate`` property names the plate is open only while it is pressed.
"""

from __future__ import annotations

from typing import Any

import pygame

from .base import Entity

PLATE_UP = (120, 112, 100)
PLATE_DOWN = (80, 200, 160)


class Liftable(Entity):
    """A tile-sized object the hero can carry."""

    def __init__(
        self,
        x: float,
        y: float,
        sprite: pygame.Surface | None = None,
        name: str = "",
        properties: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(x, y, 16, 16, sprite, name=name, properties=properties)
        #: Stable id within its map (object name, else ``#<object id>``) for persistence.
        self.key: str = name

    def tile(self, tile_size: int) -> tuple[int, int]:
        """The tile the object's centre is on."""
        cx, cy = self.center
        return (int(cx // tile_size), int(cy // tile_size))

    def place_on_tile(self, tx: int, ty: int, tile_size: int) -> None:
        """Snap onto tile (tx, ty)."""
        self.x = float(tx * tile_size)
        self.y = float(ty * tile_size)


class Plate(Entity):
    """A pressure plate. ``pressed`` is updated by the world scene."""

    def __init__(
        self,
        x: float,
        y: float,
        sprite: pygame.Surface | None = None,
        name: str = "",
        properties: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(x, y, 16, 16, sprite, name=name, properties=properties)
        self.pressed = False

    @property
    def bottom(self) -> float:
        """Plates lie flat: always drawn under everything else."""
        return -1e9

    def holds(self, ent: Entity) -> bool:
        """True if ``ent``'s centre lies on the plate."""
        cx, cy = ent.center
        return self.x <= cx < self.x + self.w and self.y <= cy < self.y + self.h

    def draw(self, surface: pygame.Surface, offset: tuple[int, int]) -> None:
        """A sprite if given, else a drawn stone slab that lights up when pressed."""
        if self.sprite is not None:
            super().draw(surface, offset)
        rect = pygame.Rect(
            round(self.x) - offset[0], round(self.y) - offset[1], int(self.w), int(self.h)
        ).inflate(-2, -2)
        if self.sprite is None:
            pygame.draw.rect(surface, (60, 56, 52), rect)
        pygame.draw.rect(surface, PLATE_DOWN if self.pressed else PLATE_UP, rect, 1)
