"""The hero: 4-direction movement, dash (``w``/``b``), strike (``x``), cleave (``dd``),
rewind (``u``), carrying a lifted object (``yy``/``p``), coins and hearts."""

from __future__ import annotations

import math
from collections import deque
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
HP_PER_HEART = 2
CLEAVE_REACH_TILES = 8  # the cleave covers this many tiles on each side of the hero
CLEAVE_ACTIVE = 0.15  # how long the cleave flash is drawn
CLEAVE_COOLDOWN = 0.6
TRAIL_SAMPLE = 0.05  # rewind trail sampling period (s)
TRAIL_SAMPLES = 60  # 60 x 50 ms = 3 s of movement
REWIND_TIME = 0.3  # how long playing the trail back takes
REWIND_IFRAME_PAD = 0.1
MAX_U_CHARGES = 3


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
        # cleave (dd)
        self.cleave_timer = 0.0  # > 0 while the cleave flash shows
        self.cleave_cooldown = 0.0
        self.cleave_rect: tuple[float, float, float, float] | None = None
        # rewind (u)
        self.trail: deque[tuple[float, float]] = deque(maxlen=TRAIL_SAMPLES)
        self.trail_clock = 0.0
        self.u_charges = MAX_U_CHARGES
        self.rewind_path: list[tuple[float, float]] = []
        self.rewind_time = 0.0
        # inventory
        self.coins = 0
        self.items: list[str] = []
        self.carrying: Entity | None = None

    # ---- hearts -----------------------------------------------------------------------
    @property
    def hearts_max(self) -> int:
        """Number of heart containers (each holds ``HP_PER_HEART`` hp)."""
        return max(1, self.max_hp // HP_PER_HEART)

    @hearts_max.setter
    def hearts_max(self, value: int) -> None:
        self.max_hp = max(1, int(value)) * HP_PER_HEART
        self.hp = min(self.hp, self.max_hp)

    def heal(self, hp: int) -> int:
        """Restore up to ``hp`` hit points; returns how many were actually restored."""
        before = self.hp
        self.hp = min(self.max_hp, self.hp + max(0, hp))
        return self.hp - before

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
        """True while i-frames are running (dashing, rewinding or recently hurt)."""
        return self.iframes > 0

    @property
    def rewinding(self) -> bool:
        """True while ``u`` is playing the movement trail back."""
        return bool(self.rewind_path)

    def cleave_box(self) -> tuple[float, float, float, float]:
        """The ``dd`` hitbox: the hero's whole row (facing left/right) or column (up/down),
        ``CLEAVE_REACH_TILES`` tiles to each side."""
        cx, cy = self.center
        reach = CLEAVE_REACH_TILES * TILE
        if self.facing[0] != 0:
            return (cx - reach, cy - TILE / 2, 2 * reach, TILE)
        return (cx - TILE / 2, cy - reach, TILE, 2 * reach)

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

    def cleave(self) -> tuple[float, float, float, float] | None:
        """Start a ``dd`` cleave. Returns its hitbox, or None while on cooldown."""
        if self.cleave_cooldown > 0 or self.rewinding:
            return None
        self.cleave_cooldown = CLEAVE_COOLDOWN
        self.cleave_timer = CLEAVE_ACTIVE
        self.cleave_rect = self.cleave_box()
        return self.cleave_rect

    def rewind(self) -> bool:
        """``u``: replay the last 3 s of movement backwards. Uses one charge."""
        if self.u_charges <= 0 or self.rewinding or len(self.trail) < 2:
            return False
        self.u_charges -= 1
        path = list(self.trail)
        path.reverse()
        self.rewind_path = path
        self.rewind_time = 0.0
        self.trail.clear()
        self.dash_time = 0.0
        self.knockback_time = 0.0
        self.attack_phase = None
        self.queued_strikes = 0
        self.iframes = max(self.iframes, REWIND_TIME + REWIND_IFRAME_PAD)
        return True

    def refill_charges(self) -> None:
        """Rest at a waystone: ``u`` charges back to full."""
        self.u_charges = MAX_U_CHARGES

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
        self.cleave_cooldown = max(0.0, self.cleave_cooldown - dt)
        self.cleave_timer = max(0.0, self.cleave_timer - dt)
        if self.rewinding:
            self._tick_rewind(dt)
            return
        self._record_trail(dt)  # sample the position before this step's movement
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

    def _record_trail(self, dt: float) -> None:
        self.trail_clock += dt
        if self.trail_clock >= TRAIL_SAMPLE - 1e-9 or not self.trail:
            self.trail_clock = 0.0
            self.trail.append((self.x, self.y))

    def _tick_rewind(self, dt: float) -> None:
        """Move along the reversed trail; the whole trail plays back in ``REWIND_TIME``."""
        self.rewind_time += dt
        path = self.rewind_path
        frac = min(1.0, self.rewind_time / REWIND_TIME)
        idx = min(len(path) - 1, int(frac * (len(path) - 1)))
        self.x, self.y = path[idx]
        self.moving = False
        self.bob = 0
        if frac >= 1.0:
            self.x, self.y = path[-1]
            self.rewind_path = []
            self.trail.clear()
            self.trail_clock = 0.0

    def draw(self, surface: pygame.Surface, offset: tuple[int, int]) -> None:
        """Draw the hero (blinking during hurt i-frames), any carried object above the head,
        the strike arc and the cleave flash."""
        hurt_blink = (
            self.iframes > 0 and not self.dashing and not self.rewinding
            and int(self.iframes * 20) % 2
        )
        if self.rewinding:
            self._draw_rewind_ghosts(surface, offset)
        if not hurt_blink:
            super().draw(surface, offset)
        carried = self.carrying
        if carried is not None and carried.sprite is not None:
            sw, sh = carried.sprite.get_size()
            sx = round(self.x + self.w / 2 - sw / 2) - offset[0]
            sy = round(self.y + self.h - 16 - sh + 4) - offset[1] + self.bob
            surface.blit(carried.sprite, (sx, sy))
        if self.cleave_timer > 0 and self.cleave_rect is not None:
            x, y, w, h = self.cleave_rect
            r = pygame.Rect(round(x) - offset[0], round(y) - offset[1], int(w), int(h))
            pygame.draw.rect(surface, (255, 240, 170), r.inflate(0, -10), 1)
            if w > h:
                pygame.draw.line(surface, (255, 255, 255), r.midleft, r.midright)
            else:
                pygame.draw.line(surface, (255, 255, 255), r.midtop, r.midbottom)
        box = self.attack_box()
        if box is not None:
            x, y, w, h = box
            r = pygame.Rect(round(x) - offset[0], round(y) - offset[1], int(w), int(h))
            pygame.draw.rect(surface, (255, 240, 170), r.inflate(-6, -6), 1)
            pygame.draw.line(surface, (255, 255, 255), r.topleft, r.bottomright)

    def _draw_rewind_ghosts(self, surface: pygame.Surface, offset: tuple[int, int]) -> None:
        for gx, gy in self.rewind_path[:: max(1, len(self.rewind_path) // 6)]:
            r = pygame.Rect(round(gx) - offset[0], round(gy) - offset[1], int(self.w), int(self.h))
            pygame.draw.rect(surface, (150, 140, 240), r, 1)
