"""Companions: small friends that follow the hero (Moth, the reformed bug).

A :class:`Companion` keeps its own short history of the player's positions and trails
about :data:`FOLLOW_DISTANCE` px behind along that path. It hovers (sine bob), flips with
its direction of travel, animates its two frames at :data:`ANIM_FPS`, never collides and
never blocks. Its :attr:`bottom` sorts it just after the player so it draws on top.

Wiring for ``WorldScene`` (the orchestrator adds it; this module does not touch the scene)::

    # on load / when the flag appears (e.g. in __init__ and after dialogue):
    if "moth_joined" in self.game.progress.flags and self.companion is None:
        self.companion = Companion.moth()          # self.companion: Companion | None = None
    # in update(), after the player moves:
    if self.companion is not None:
        self.companion.update(dt, self.player)
    # in draw(), the entity list:
    entities = [*self.all_entities(), self.player, *([self.companion] if self.companion else [])]

While the companion is active, also hide (or skip spawning) the static ``npc Moth`` on
``little_tilde`` so there are not two moths. After a map transition call
:meth:`Companion.reset` so the moth reappears beside the hero instead of flying across.
"""

from __future__ import annotations

import math
from collections import deque
from typing import Any

import pygame

from . import sprites
from .base import Entity

FOLLOW_DISTANCE = 20.0  # px behind the player along the player's path
SAMPLE_SPACING = 2.0  # px between recorded path points
HISTORY = 64  # path points kept (64 x 2 px = 128 px of path)
FOLLOW_RATE = 10.0  # 1/s, exponential approach towards the trail point
SNAP_DISTANCE = 96.0  # further than this (a teleport or map change): jump, don't fly
ANIM_FPS = 6.0
BOB_HZ = 1.2
BOB_PIXELS = 2.0
HOVER = 6  # px the sprite floats above its (tiny) hitbox
SPRITE_FACES_LEFT = True  # like the Kenney heroes
FLIP_DEADZONE = 0.05  # px per step of horizontal travel needed to change facing


class Companion(Entity):
    """A non-solid follower that trails the player."""

    solid = False

    def __init__(
        self,
        frames: list[pygame.Surface] | None = None,
        name: str = "companion",
        x: float = 0.0,
        y: float = 0.0,
    ) -> None:
        sprite = frames[0] if frames else None
        super().__init__(x, y, 6, 6, sprite, name=name)
        self.sprite_frames: list[pygame.Surface] = list(frames or [])
        self.frame = 0
        self.anim_time = 0.0
        self.path: deque[tuple[float, float]] = deque(maxlen=HISTORY)
        self.placed = False
        self._sort_bottom = self.y + self.h

    @classmethod
    def moth(cls) -> Companion:
        """Moth, with the committed ``assets/sprites/moth.png`` two-frame sheet."""
        from coderogue.app import resource_path

        frames = sprites.load_sheet(resource_path("assets", "sprites", "moth.png"), 16)
        return cls(frames, name="Moth")

    @property
    def bottom(self) -> float:  # type: ignore[override]
        """Sort key: just below the followed player's feet, so the companion draws on top."""
        return self._sort_bottom

    def reset(self) -> None:
        """Forget the trail; the next update places the companion beside the player again."""
        self.path.clear()
        self.placed = False

    def _target(self) -> tuple[float, float]:
        """The point ``FOLLOW_DISTANCE`` px back along the recorded path (oldest if short)."""
        points = list(self.path)
        remaining = FOLLOW_DISTANCE
        for i in range(len(points) - 1, 0, -1):
            (x1, y1), (x0, y0) = points[i], points[i - 1]
            seg = math.hypot(x1 - x0, y1 - y0)
            if seg >= remaining:
                t = remaining / seg
                return (x1 + (x0 - x1) * t, y1 + (y0 - y1) * t)
            remaining -= seg
        return points[0]

    def update(self, dt: float, world: Any) -> None:  # type: ignore[override]
        """Advance one step. ``world`` is the followed entity (the player)."""
        player: Entity = world
        pcx, pcy = player.center
        self._sort_bottom = player.bottom + 0.5
        if not self.placed:
            fx, fy = getattr(player, "facing", (0, 1))
            self.place_center(pcx - fx * FOLLOW_DISTANCE, pcy - fy * FOLLOW_DISTANCE)
            self.path.clear()
            self.path.append(self.center)
            self.path.append((pcx, pcy))
            self.placed = True
        last = self.path[-1]
        if math.hypot(pcx - last[0], pcy - last[1]) >= SAMPLE_SPACING:
            self.path.append((pcx, pcy))
        tx, ty = self._target()
        cx, cy = self.center
        if math.hypot(tx - cx, ty - cy) > SNAP_DISTANCE:
            self.place_center(tx, ty)
            dx = 0.0
        else:
            k = 1.0 - math.exp(-FOLLOW_RATE * dt)
            dx, dy = (tx - cx) * k, (ty - cy) * k
            self.place_center(cx + dx, cy + dy)
        if abs(dx) > FLIP_DEADZONE:
            moving_right = dx > 0
            self.flip_x = moving_right if SPRITE_FACES_LEFT else not moving_right
        self.anim_time += dt
        if self.sprite_frames:
            self.frame = int(self.anim_time * ANIM_FPS) % len(self.sprite_frames)
            self.sprite = self.sprite_frames[self.frame]
        self.bob = round(math.sin(self.anim_time * BOB_HZ * 2 * math.pi) * BOB_PIXELS) - HOVER
