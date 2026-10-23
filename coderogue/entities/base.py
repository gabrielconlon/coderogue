"""Base entity: float position, AABB hitbox, a sprite and a draw routine."""

from __future__ import annotations

from typing import Any

import pygame


class Entity:
    """Something that lives in the world.

    ``x``/``y`` is the top-left of the *hitbox* (``w`` x ``h``) in world pixels, as floats.
    The sprite (usually 16x16) is drawn bottom-centre aligned with the hitbox so a small
    hitbox sits at the character's feet.
    """

    solid: bool = False

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
        self.x = float(x)
        self.y = float(y)
        self.w = float(w)
        self.h = float(h)
        self.sprite = sprite
        self.name = name
        self.properties: dict[str, Any] = dict(properties or {})
        self.alive = True
        self.flip_x = False
        self.bob = 0  # vertical sprite offset in pixels (walk animation)
        self.visible = True

    @property
    def box(self) -> tuple[float, float, float, float]:
        """Hitbox as (x, y, w, h)."""
        return (self.x, self.y, self.w, self.h)

    @property
    def rect(self) -> pygame.FRect:
        """Hitbox as a pygame FRect."""
        return pygame.FRect(self.x, self.y, self.w, self.h)

    @property
    def center(self) -> tuple[float, float]:
        """Hitbox centre."""
        return (self.x + self.w / 2, self.y + self.h / 2)

    @property
    def bottom(self) -> float:
        """Hitbox bottom edge (used for draw ordering)."""
        return self.y + self.h

    def place_center(self, cx: float, cy: float) -> None:
        """Move so the hitbox centre is at (cx, cy)."""
        self.x = cx - self.w / 2
        self.y = cy - self.h / 2

    def update(self, dt: float, world: Any) -> None:
        """Advance one fixed step. ``world`` is the owning scene (has ``collision``)."""

    def draw(self, surface: pygame.Surface, offset: tuple[int, int]) -> None:
        """Draw the sprite at its world position minus the camera ``offset``."""
        if self.sprite is None or not self.visible:
            return
        sprite = pygame.transform.flip(self.sprite, True, False) if self.flip_x else self.sprite
        sw, sh = sprite.get_size()
        sx = round(self.x + self.w / 2 - sw / 2) - offset[0]
        sy = round(self.y + self.h - sh) - offset[1] + self.bob
        surface.blit(sprite, (sx, sy))


class StaticProp(Entity):
    """A non-interactive decoration spawned from a map object (npc, chest, door for now)."""

    def __init__(self, x: float, y: float, sprite: pygame.Surface | None, **kw: Any) -> None:
        super().__init__(x, y, 16, 16, sprite, **kw)
