"""Enemies. For now a single random-walking ``Wanderer`` bug."""

from __future__ import annotations

import math
import random
from typing import Any

import pygame

from coderogue.world.collision import move_box

from .base import Entity

DIRECTIONS: tuple[tuple[int, int], ...] = ((1, 0), (-1, 0), (0, 1), (0, -1), (0, 0))


class Wanderer(Entity):
    """Random-walk enemy: picks a direction every so often, turns when it bumps a wall.

    ``hurt()`` applies damage with brief invulnerability and knockback; at 0 hp it dies
    (``alive`` becomes False and the scene removes it).
    """

    contact_damage = 1

    def __init__(
        self,
        x: float,
        y: float,
        sprite: pygame.Surface | None = None,
        hp: int = 3,
        speed: float = 30.0,
        rng: random.Random | None = None,
        **kw: Any,
    ) -> None:
        super().__init__(x, y, 12, 10, sprite, **kw)
        self.max_hp = hp
        self.hp = hp
        self.speed = speed
        self.rng = rng or random.Random()
        self.direction: tuple[int, int] = (0, 0)
        self.turn_timer = 0.0
        self.iframes = 0.0
        self.knockback: tuple[float, float] = (0.0, 0.0)
        self.knockback_time = 0.0
        self.anim_time = self.rng.random()

    def _pick_direction(self, exclude: tuple[int, int] | None = None) -> None:
        choices = [d for d in DIRECTIONS if d != exclude]
        self.direction = self.rng.choice(choices)
        self.turn_timer = self.rng.uniform(0.8, 2.0)

    def hurt(self, damage: int = 1, source: tuple[float, float] | None = None) -> bool:
        """Take ``damage`` (knocked away from ``source``). Returns True if it landed."""
        if self.iframes > 0 or not self.alive:
            return False
        self.hp -= damage
        self.iframes = 0.25
        if source is not None:
            cx, cy = self.center
            dx, dy = cx - source[0], cy - source[1]
            d = math.hypot(dx, dy) or 1.0
            self.knockback = (dx / d * 140.0, dy / d * 140.0)
            self.knockback_time = 0.15
        if self.hp <= 0:
            self.alive = False
        return True

    def update(self, dt: float, world: Any) -> None:
        """Random walk with wall bumps."""
        self.iframes = max(0.0, self.iframes - dt)
        self.anim_time += dt
        if self.knockback_time > 0:
            self.knockback_time -= dt
            vx, vy = self.knockback[0] * dt, self.knockback[1] * dt
        else:
            self.turn_timer -= dt
            if self.turn_timer <= 0:
                self._pick_direction()
            vx = self.direction[0] * self.speed * dt
            vy = self.direction[1] * self.speed * dt
        if vx or vy:
            res = move_box(world.collision, self.x, self.y, self.w, self.h, vx, vy)
            self.x, self.y = res.x, res.y
            if (res.hit_x or res.hit_y) and self.knockback_time <= 0:
                self._pick_direction(exclude=self.direction)
        if self.direction[0]:
            self.flip_x = self.direction[0] > 0
        self.bob = -1 if self.direction != (0, 0) and int(self.anim_time / 0.2) % 2 else 0

    def draw(self, surface: pygame.Surface, offset: tuple[int, int]) -> None:
        """Draw, flashing white while invulnerable after a hit."""
        if self.iframes > 0 and self.sprite is not None:
            flash = self.sprite.copy()
            flash.fill((255, 255, 255, 0), special_flags=pygame.BLEND_RGBA_MAX)
            original = self.sprite
            self.sprite = flash
            super().draw(surface, offset)
            self.sprite = original
        else:
            super().draw(surface, offset)
