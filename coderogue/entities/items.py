"""Chests and pickups.

* ``chest`` objects open once on INTERACT, giving ``coins`` (int) and/or ``item`` (string).
* ``potion`` pickups heal ``heal`` hp (default 2, one heart) when walked over, unless the
  hero is already at full health.
* ``coin`` pickups add ``value`` coins (default 1) when walked over.

Taken pickups and opened chests are remembered by the world scene (as progress flags) so
they stay taken when the map is re-entered.
"""

from __future__ import annotations

import math
from typing import Any

import pygame

from .base import Entity

INTERACT_REACH = 6


class Chest(Entity):
    """A chest that can be opened once."""

    def __init__(
        self,
        x: float,
        y: float,
        sprite: pygame.Surface | None = None,
        open_sprite: pygame.Surface | None = None,
        name: str = "",
        properties: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(x, y, 16, 16, sprite, name=name, properties=properties)
        self.open_sprite = open_sprite
        self.opened = False
        self.coins = int(self.properties.get("coins", 0) or 0)
        self.item = str(self.properties.get("item") or "")

    def interact_box(self) -> tuple[float, float, float, float]:
        """Area in which the hero can open the chest."""
        r = INTERACT_REACH
        return (self.x - r, self.y - r, self.w + 2 * r, self.h + 2 * r)

    def open(self) -> tuple[int, str] | None:
        """Open the chest: returns ``(coins, item)`` the first time, None afterwards."""
        if self.opened:
            return None
        self.opened = True
        if self.open_sprite is not None:
            self.sprite = self.open_sprite
        return (self.coins, self.item)


class Pickup(Entity):
    """A coin or potion lying on the ground; collected on overlap."""

    def __init__(
        self,
        x: float,
        y: float,
        kind: str,
        sprite: pygame.Surface | None = None,
        name: str = "",
        properties: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(x, y, 10, 10, sprite, name=name, properties=properties)
        self.kind = kind
        default = 2 if kind == "potion" else 1
        key = "heal" if kind == "potion" else "value"
        self.amount = int(self.properties.get(key, default) or default)
        self.anim_time = 0.0

    def update(self, dt: float, world: Any) -> None:
        """Gentle bob."""
        self.anim_time += dt
        self.bob = round(math.sin(self.anim_time * 4.0))
