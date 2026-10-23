"""Doors: exits to other maps, and gates that open from flags, puzzles or pressure plates.

Spawned from ``door`` map objects. Properties:

* ``target``: map stem under ``content/maps`` (e.g. ``"echo_vale"``). Without a target the
  door is a *gate*: solid while locked, passable (drawn faintly) once open.
* ``spawn``: name of the ``player_spawn`` object in the target map (default ``"spawn"``).
* ``locked_by``: a progress flag that must be set before the door opens.
* ``requires_solved``: a puzzle id that must be solved before the door opens.
* ``plate``: name of a ``plate`` object; the door is open only while a liftable rests on it.

The world scene computes :attr:`Door.locked` each step via
:func:`coderogue.world.transitions.door_lock_reason`.
"""

from __future__ import annotations

from typing import Any

import pygame

from .altar import dim_sprite
from .base import Entity

TOUCH_REACH = 2  # px: a locked (solid) door is "touched" when the hero is this close
NULL_WASH = (120, 120, 132, 110)


class Door(Entity):
    """A door or gate occupying one map object rectangle (usually one 16x16 tile)."""

    def __init__(
        self,
        x: float,
        y: float,
        w: float = 16,
        h: float = 16,
        sprite: pygame.Surface | None = None,
        name: str = "",
        properties: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(x, y, w or 16, h or 16, sprite, name=name, properties=properties)
        props = self.properties
        self.target: str = str(props.get("target") or "")
        self.spawn: str = str(props.get("spawn") or "spawn")
        self.locked_by: str = str(props.get("locked_by") or "")
        self.requires_solved: str = str(props.get("requires_solved") or "")
        self.plate: str = str(props.get("plate") or "")
        self.locked = bool(self.locked_by or self.requires_solved or self.plate)
        self.lock_reason = ""
        self._grey: pygame.Surface | None = None

    @property
    def is_exit(self) -> bool:
        """True if walking through this door loads another map."""
        return bool(self.target)

    def touch_box(self) -> tuple[float, float, float, float]:
        """Slightly larger than the door, so touching a solid locked door registers."""
        r = TOUCH_REACH
        return (self.x - r, self.y - r, self.w + 2 * r, self.h + 2 * r)

    def tiles(self, tile_size: int) -> list[tuple[int, int]]:
        """Tile coordinates covered by the door rectangle."""
        x0, y0 = int(self.x // tile_size), int(self.y // tile_size)
        x1 = int((self.x + self.w - 1) // tile_size)
        y1 = int((self.y + self.h - 1) // tile_size)
        return [(tx, ty) for ty in range(y0, y1 + 1) for tx in range(x0, x1 + 1)]

    def draw(self, surface: pygame.Surface, offset: tuple[int, int]) -> None:
        """Locked: greyed with a Null-wash. Open gate: faint. Open exit: normal."""
        rect = pygame.Rect(
            round(self.x) - offset[0], round(self.y) - offset[1], int(self.w), int(self.h)
        )
        if self.sprite is None:
            color = (90, 90, 100) if self.locked else (150, 110, 70)
            pygame.draw.rect(surface, color, rect, 0 if self.locked else 1)
        elif self.locked:
            if self._grey is None:
                self._grey = dim_sprite(self.sprite)
            for ty in range(rect.top, rect.bottom, 16):
                for tx in range(rect.left, rect.right, 16):
                    surface.blit(self._grey, (tx, ty))
        elif not self.is_exit:
            faint = self.sprite.copy()
            faint.set_alpha(70)
            surface.blit(faint, rect.topleft)
        else:
            for ty in range(rect.top, rect.bottom, 16):
                for tx in range(rect.left, rect.right, 16):
                    surface.blit(self.sprite, (tx, ty))
        if self.locked:
            wash = pygame.Surface(rect.size, pygame.SRCALPHA)
            wash.fill(NULL_WASH)
            surface.blit(wash, rect.topleft)
