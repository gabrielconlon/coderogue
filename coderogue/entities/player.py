"""The hero: 4-direction movement, dash (``w``/``b``) and strike (``x``)."""

from __future__ import annotations

import math
from typing import Any

import pygame

from coderogue.world.collision import CollisionGrid, move_box

from .base import Entity

TILE = 16
SPEED = 90.0  # px/s
DASH_SPEED = 240.0  # px/s
DASH_TILES = 2  # default dash distance
MAX_DASH_TILES = 6
DASH_IFRAME_PAD = 0.08  # i-frames last this long after the dash ends
DASH_COOLDOWN = 0.35  # after the dash ends
ATTACK_ACTIVE = 0.15  # hitbox lifetime
ATTACK_RECOVERY = 0.35  # after the hitbox, before the next strike
MAX_QUEUED_STRIKES = 9
HURT_IFRAMES = 0.8
KNOCKBACK_SPEED = 160.0
KNOCKBACK_TIME = 0.12
WALK_FRAME_TIME = 0.15
SPRITE_FACES_LEFT = True  # Kenney Tiny Dungeon characters look left


def _sign(v: float) -> int:
    return (v > 0) - (v < 0)


class Player(Entity):
    """Player-controlled hero.

    Drive it each fixed step with ``update(dt, world, move=(dx, dy))`` where ``dx``/``dy``
    are -1/0/1 from held keys; call :meth:`attack` and :meth:`dash` on key presses.
    ``world`` only needs a ``collision`` attribute (a :class:`CollisionGrid`).
    """

    def __init__(self, x: float, y: float, sprite: pygame.Surface | None = None) -> None:
        super().__init__(x, y, 10, 10, sprite, name="player")
        self.facing: tuple[int, int] = (0, 1)
        self.max_hp = 6
        self.hp = self.max_hp
        self.moving = False
        self.anim_time = 0.0
        # dash
        self.dash_time = 0.0
        self.dash_dir: tuple[int, int] = (0, 0)
        self.dash_cooldown = 0.0
        # attack
        self.attack_phase: str | None = None  # "active" | "recovery" | None
        self.attack_timer = 0.0
        self.queued_strikes = 0
        self.strike_id = 0
        self.struck: set[int] = set()  # ids hit by the current strike
        # damage
        self.iframes = 0.0
        self.knockback_time = 0.0
        self.knockback: tuple[float, float] = (0.0, 0.0)

    # ---- state queries ----------------------------------------------------------------
    @property
    def dashing(self) -> bool:
        """True while a dash is moving the player."""
        return self.dash_time > 0

    @property
    def attacking(self) -> bool:
        """True during a strike's active or recovery phase."""
        return self.attack_phase is not None

    @property
    def invulnerable(self) -> bool:
        """True while i-frames are running (dashing or recently hurt)."""
        return self.iframes > 0

    def attack_box(self) -> tuple[float, float, float, float] | None:
        """The strike hitbox (one tile in the facing direction) while active, else None."""
        if self.attack_phase != "active":
            return None
        cx, cy = self.center
        fx, fy = self.facing
        return (cx + fx * TILE - TILE / 2, cy + fy * TILE - TILE / 2, TILE, TILE)

    # ---- commands ---------------------------------------------------------------------
    def attack(self, count: int = 1) -> None:
        """Queue ``count`` strikes (``3x`` queues three)."""
        self.queued_strikes = min(MAX_QUEUED_STRIKES, self.queued_strikes + max(1, count))
        self._try_start_strike()

    def dash(self, forward: bool = True, tiles: int | None = None) -> bool:
        """Dash along (``w``) or against (``b``) the facing. Returns False if not allowed."""
        fx, fy = self.facing
        direction = (fx, fy) if forward else (-fx, -fy)
        return self._start_dash(direction, tiles, set_facing=False)

    def dash_toward(self, direction: tuple[int, int], tiles: int) -> bool:
        """Dash ``tiles`` tiles in ``direction`` and face it (``3j``)."""
        return self._start_dash(direction, tiles, set_facing=True)

    def _start_dash(
        self, direction: tuple[int, int], tiles: int | None, set_facing: bool
    ) -> bool:
        if self.dashing or self.dash_cooldown > 0 or self.attack_phase == "active":
            return False
        if direction == (0, 0):
            return False
        n = DASH_TILES if tiles is None else max(1, min(MAX_DASH_TILES, tiles))
        if set_facing:
            self._set_facing(direction)
        # cancel recovery and any queued strikes: the dash is the new intent
        self.attack_phase = None
        self.queued_strikes = 0
        self.dash_dir = direction
        self.dash_time = n * TILE / DASH_SPEED
        self.iframes = max(self.iframes, self.dash_time + DASH_IFRAME_PAD)
        return True

    def hurt(self, damage: int, source: tuple[float, float] | None = None) -> bool:
        """Take damage unless invulnerable. Returns True if damage was applied."""
        if self.invulnerable or not self.alive:
            return False
        self.hp -= damage
        self.iframes = HURT_IFRAMES
        if source is not None:
            cx, cy = self.center
            dx, dy = cx - source[0], cy - source[1]
            d = math.hypot(dx, dy) or 1.0
            self.knockback = (dx / d * KNOCKBACK_SPEED, dy / d * KNOCKBACK_SPEED)
            self.knockback_time = KNOCKBACK_TIME
        return True

    # ---- simulation -------------------------------------------------------------------
    def _set_facing(self, direction: tuple[int, int]) -> None:
        self.facing = direction
        if direction[0] != 0:
            self.flip_x = (direction[0] > 0) == SPRITE_FACES_LEFT

    def _update_facing(self, move: tuple[int, int]) -> None:
        dx, dy = move
        fx, fy = self.facing
        if (fx != 0 and fx == dx) or (fy != 0 and fy == dy):
            return  # keep current facing while it is still one of the held directions
        self._set_facing((dx, 0) if dx else (0, dy))

    def _try_start_strike(self) -> None:
        if self.attack_phase is None and self.queued_strikes > 0 and not self.dashing:
            self.queued_strikes -= 1
            self.attack_phase = "active"
            self.attack_timer = ATTACK_ACTIVE
            self.strike_id += 1
            self.struck = set()

    def _tick_attack(self, dt: float) -> None:
        if self.attack_phase is None:
            self._try_start_strike()
            return
        self.attack_timer -= dt
        if self.attack_timer > 1e-9:
            return
        if self.attack_phase == "active":
            self.attack_phase = "recovery"
            self.attack_timer += ATTACK_RECOVERY
            if self.attack_timer > 1e-9:
                return
        self.attack_phase = None
        self._try_start_strike()

    def update(self, dt: float, world: Any, move: tuple[int, int] = (0, 0)) -> None:
        """Advance one fixed step with the held movement direction ``move``."""
        grid: CollisionGrid = world.collision
        self.iframes = max(0.0, self.iframes - dt)
        if not self.dashing:
            self.dash_cooldown = max(0.0, self.dash_cooldown - dt)
        self._tick_attack(dt)

        dx, dy = _sign(move[0]), _sign(move[1])
        vx = vy = 0.0
        self.moving = False
        if self.dashing:
            step = min(dt, self.dash_time)
            vx, vy = self.dash_dir[0] * DASH_SPEED * step, self.dash_dir[1] * DASH_SPEED * step
            self.dash_time -= step
            if self.dash_time <= 1e-9:
                self.dash_time = 0.0
                self.dash_cooldown = DASH_COOLDOWN
        elif self.knockback_time > 0:
            self.knockback_time -= dt
            vx, vy = self.knockback[0] * dt, self.knockback[1] * dt
        elif (dx or dy) and self.attack_phase != "active":
            self._update_facing((dx, dy))
            scale = SPEED * dt / (math.sqrt(2) if dx and dy else 1.0)
            vx, vy = dx * scale, dy * scale
            self.moving = True

        if vx or vy:
            res = move_box(grid, self.x, self.y, self.w, self.h, vx, vy)
            self.x, self.y = res.x, res.y
            if self.dashing and (res.hit_x or res.hit_y):  # dashes stop at walls
                self.dash_time = 0.0
                self.dash_cooldown = DASH_COOLDOWN

        if self.moving:
            self.anim_time += dt
            self.bob = -1 if int(self.anim_time / WALK_FRAME_TIME) % 2 else 0
        else:
            self.anim_time = 0.0
            self.bob = 0

    def draw(self, surface: pygame.Surface, offset: tuple[int, int]) -> None:
        """Draw the hero (blinking during hurt i-frames) and the strike arc when active."""
        hurt_blink = self.iframes > 0 and not self.dashing and int(self.iframes * 20) % 2
        if not hurt_blink:
            super().draw(surface, offset)
        box = self.attack_box()
        if box is not None:
            x, y, w, h = box
            r = pygame.Rect(round(x) - offset[0], round(y) - offset[1], int(w), int(h))
            pygame.draw.rect(surface, (255, 240, 170), r.inflate(-6, -6), 1)
            pygame.draw.line(surface, (255, 255, 255), r.topleft, r.bottomright)
