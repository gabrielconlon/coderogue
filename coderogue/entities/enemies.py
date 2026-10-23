"""Enemies: the bug roster (Typo-mite, Off-by-One, Leak, Looper, Null-wisp, Stamp-golem).

Contracts (shared with the world scene, see also :mod:`coderogue.entities.combat`):

* ``spawn_enemy(obj, sprites_module) -> Enemy`` builds an enemy from a map object. The
  class comes from ``obj.properties["kind"]`` (``typo_mite`` | ``off_by_one`` | ``leak`` |
  ``looper`` | ``null_wisp`` | ``stamp_golem`` | ``grubble`` | ``ouroboros`` |
  ``hollow_archivist``; anything else is a ``wanderer``). Properties ``hp``, ``speed`` and
  ``tile`` (or ``sprite``) override the defaults; ``sheet: town`` picks the Tiny Town sheet.
  ``sprites_module`` is :mod:`coderogue.entities.sprites` (or ``None`` for no sprites).
* ``Enemy.update(dt, world)`` reads ``world.collision`` and, when present, ``world.player``,
  ``world.enemies`` and ``world.locked_target`` (the entity locked with ``v``, or None).
  New enemies (Leak splits, boss minions) are added with :func:`add_enemy`, which calls
  ``world.spawn_enemy_instance(enemy)`` if the world has it, else appends to
  ``world.enemies``. The list may therefore grow while the scene iterates it.
* ``Enemy.hurt(damage, source, kind="strike")``: ``kind`` is ``"strike"`` (``x``),
  ``"cleave"`` (``dd``) or ``"dash"``. ``source`` is an entity or an ``(x, y)`` point (the
  knockback origin) or None. Returns True when damage was applied. Loopers take double
  damage from cleaves, Null-wisps ignore hits unless ``world.locked_target is self``, and
  Stamp-golems ignore everything (showing a "stamped" flash).
* Knockback: 1.5 tiles over 0.15 s, away from ``source``, stopped by walls.
* Death: ``alive`` becomes False and ``world.on_enemy_killed(enemy)`` is called once if the
  world defines it (via the last world the enemy saw in ``update``/``bind``, or by
  :func:`coderogue.entities.combat.reap`).
* ``Enemy.hazards()`` lists ``(entity, damage)`` pairs that hurt the player on overlap and
  ``Enemy.targets()`` lists the entities a player attack can hit (bosses add their crown
  letters, segments and cards). :mod:`coderogue.entities.combat` uses both.
"""

from __future__ import annotations

import math
import random
from typing import Any

import pygame

from coderogue.world.collision import move_box

from .base import Entity

TILE = 16
DIRECTIONS: tuple[tuple[int, int], ...] = ((1, 0), (-1, 0), (0, 1), (0, -1), (0, 0))

KNOCKBACK_TILES = 1.5
KNOCKBACK_TIME = 0.15
KNOCKBACK_SPEED = KNOCKBACK_TILES * TILE / KNOCKBACK_TIME  # 160 px/s
HIT_IFRAMES = 0.25
ATTACK_KINDS = ("strike", "cleave", "dash")

# Sprite tile ids (Tiny Dungeon unless noted).
TILE_RED_SPIDER = 110
TILE_BROWN_SPIDER = 122
TILE_GREEN_GHOST = 108
TILE_BAT = 120
TILE_GREY_GHOST = 121
TILE_TOWN_GOLEM = 94  # Tiny Town sheet

# Off-by-One
LUNGE_RANGE = 5 * TILE
LUNGE_AIM_TIME = 0.4
LUNGE_SPEED = 220.0
LUNGE_REST = 0.6
LUNGE_COOLDOWN = 1.5
LUNGE_MAX_TIME = 1.0

# Leak
SPLIT_TIME = 6.0
MAX_LEAKS = 16

# Null-wisp
WISP_ALPHA = 102  # 40%
WISP_SIGHT = 8 * TILE

STAMP_FLASH = 0.5


def source_point(source: Any) -> tuple[float, float] | None:
    """The knockback origin for ``source`` (an entity's centre, a point, or None)."""
    if source is None:
        return None
    center = getattr(source, "center", None)
    if center is not None:
        return (float(center[0]), float(center[1]))
    return (float(source[0]), float(source[1]))


def add_enemy(world: Any, enemy: Enemy) -> None:
    """Add ``enemy`` to the world (``world.spawn_enemy_instance`` or ``world.enemies``)."""
    spawn = getattr(world, "spawn_enemy_instance", None)
    if callable(spawn):
        spawn(enemy)
        return
    enemies = getattr(world, "enemies", None)
    if enemies is not None:
        enemies.append(enemy)


class Enemy(Entity):
    """Base bug: hp, hit i-frames, knockback, death reporting and a flash-on-hit draw.

    Subclasses implement :meth:`think` (called each step when not being knocked back) and
    may override :meth:`can_be_hurt` / :meth:`damage_multiplier`.
    """

    kind = "enemy"
    contact_damage = 1
    knockback_enabled = True

    def __init__(
        self,
        x: float,
        y: float,
        sprite: pygame.Surface | None = None,
        hp: int = 3,
        speed: float = 30.0,
        rng: random.Random | None = None,
        w: float = 12,
        h: float = 10,
        **kw: Any,
    ) -> None:
        super().__init__(x, y, w, h, sprite, **kw)
        self.max_hp = hp
        self.hp = hp
        self.speed = speed
        self.rng = rng or random.Random()
        self.iframes = 0.0
        self.knockback: tuple[float, float] = (0.0, 0.0)
        self.knockback_time = 0.0
        self.anim_time = self.rng.random()
        self.alpha = 255
        self._world: Any = None
        self._death_reported = False

    # ---- world binding / death -----------------------------------------------------
    def bind(self, world: Any) -> None:
        """Remember ``world`` (for lock-on checks and death reporting)."""
        self._world = world

    def die(self) -> None:
        """Mark dead and report it to the bound world."""
        self.alive = False
        self.report_death(self._world)

    def report_death(self, world: Any) -> None:
        """Call ``world.on_enemy_killed(self)`` once, if the world has it."""
        if self._death_reported or world is None:
            return
        callback = getattr(world, "on_enemy_killed", None)
        if callable(callback):
            self._death_reported = True
            callback(self)

    # ---- combat ----------------------------------------------------------------------
    def can_be_hurt(self, kind: str) -> bool:
        """Whether an attack of ``kind`` can land right now."""
        return True

    def damage_multiplier(self, kind: str) -> int:
        """Damage factor for an attack of ``kind``."""
        return 1

    def on_hurt(self, kind: str) -> None:
        """Hook called after damage lands."""

    def hurt(self, damage: int = 1, source: Any = None, kind: str = "strike") -> bool:
        """Take ``damage`` from ``source`` with ``kind``. Returns True if it landed."""
        if not self.alive or self.iframes > 0 or not self.can_be_hurt(kind):
            return False
        self.hp -= damage * self.damage_multiplier(kind)
        self.iframes = HIT_IFRAMES
        point = source_point(source)
        if point is not None and self.knockback_enabled:
            self.apply_knockback(point)
        self.on_hurt(kind)
        if self.hp <= 0:
            self.die()
        return True

    def apply_knockback(self, point: tuple[float, float]) -> None:
        """Start a 1.5-tile knockback away from ``point``."""
        cx, cy = self.center
        dx, dy = cx - point[0], cy - point[1]
        d = math.hypot(dx, dy)
        if d == 0:
            dx, dy, d = 0.0, 1.0, 1.0
        self.knockback = (dx / d * KNOCKBACK_SPEED, dy / d * KNOCKBACK_SPEED)
        self.knockback_time = KNOCKBACK_TIME

    def hazards(self) -> list[tuple[Entity, int]]:
        """``(entity, damage)`` pairs that hurt the player on contact."""
        if self.alive and self.contact_damage > 0:
            return [(self, self.contact_damage)]
        return []

    def targets(self) -> list[Entity]:
        """Entities a player attack can hit (each has ``box`` and ``hurt``)."""
        return [self] if self.alive else []

    # ---- simulation ------------------------------------------------------------------
    def move(self, world: Any, dx: float, dy: float) -> tuple[bool, bool]:
        """Move by (dx, dy) against ``world.collision``; returns (hit_x, hit_y)."""
        if not dx and not dy:
            return (False, False)
        res = move_box(world.collision, self.x, self.y, self.w, self.h, dx, dy)
        self.x, self.y = res.x, res.y
        return (res.hit_x, res.hit_y)

    def update(self, dt: float, world: Any) -> None:
        """Tick timers, then either slide along a knockback or :meth:`think`."""
        self._world = world
        self.iframes = max(0.0, self.iframes - dt)
        self.anim_time += dt
        if self.knockback_time > 0:
            step = min(dt, self.knockback_time)
            self.knockback_time -= step
            if self.knockback_time < 1e-9:
                self.knockback_time = 0.0
            self.move(world, self.knockback[0] * step, self.knockback[1] * step)
            return
        self.think(dt, world)

    def think(self, dt: float, world: Any) -> None:
        """Per-step behaviour when not knocked back."""

    # ---- drawing ---------------------------------------------------------------------
    def draw(self, surface: pygame.Surface, offset: tuple[int, int]) -> None:
        """Draw, flashing white while invulnerable and honouring ``alpha``."""
        if self.sprite is None or not self.visible:
            return
        original = self.sprite
        sprite = original
        if self.iframes > 0:
            sprite = original.copy()
            sprite.fill((255, 255, 255, 0), special_flags=pygame.BLEND_RGBA_MAX)
        if self.alpha < 255:
            sprite = sprite.copy() if sprite is original else sprite
            sprite.set_alpha(self.alpha)
        self.sprite = sprite
        super().draw(surface, offset)
        self.sprite = original


class Wanderer(Enemy):
    """Random-walk enemy: picks a direction every so often, turns when it bumps a wall."""

    kind = "wanderer"

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
        super().__init__(x, y, sprite, hp=hp, speed=speed, rng=rng, **kw)
        self.direction: tuple[int, int] = (0, 0)
        self.turn_timer = 0.0

    def _pick_direction(self, exclude: tuple[int, int] | None = None) -> None:
        choices = [d for d in DIRECTIONS if d != exclude]
        self.direction = self.rng.choice(choices)
        self.turn_timer = self.rng.uniform(0.8, 2.0)

    def think(self, dt: float, world: Any) -> None:
        """Random walk with wall bumps."""
        self.turn_timer -= dt
        if self.turn_timer <= 0:
            self._pick_direction()
        vx = self.direction[0] * self.speed * dt
        vy = self.direction[1] * self.speed * dt
        hit_x, hit_y = self.move(world, vx, vy)
        if hit_x or hit_y:
            self._pick_direction(exclude=self.direction)
        if self.direction[0]:
            self.flip_x = self.direction[0] > 0
        self.bob = -1 if self.direction != (0, 0) and int(self.anim_time / 0.2) % 2 else 0


class TypoMite(Wanderer):
    """A stray character: wanders quickly and dies to one strike."""

    kind = "typo_mite"

    def __init__(
        self,
        x: float,
        y: float,
        sprite: pygame.Surface | None = None,
        hp: int = 1,
        speed: float = 40.0,
        rng: random.Random | None = None,
        **kw: Any,
    ) -> None:
        super().__init__(x, y, sprite, hp=hp, speed=speed, rng=rng, **kw)
        self.spawned_by: Any = None


class OffByOne(Wanderer):
    """Two-headed beetle: aims at the player, then lunges and lands one tile off its aim.

    States: ``wander`` -> ``aim`` (telegraph, ``LUNGE_AIM_TIME``) -> ``lunge`` -> ``rest``.
    ``aim_point`` is where it aimed (the player's centre at aim time) and ``landing_point``
    is ``aim_point`` shifted one tile perpendicular to the lunge.
    """

    kind = "off_by_one"

    def __init__(
        self,
        x: float,
        y: float,
        sprite: pygame.Surface | None = None,
        hp: int = 2,
        speed: float = 20.0,
        rng: random.Random | None = None,
        **kw: Any,
    ) -> None:
        super().__init__(x, y, sprite, hp=hp, speed=speed, rng=rng, **kw)
        self.state = "wander"
        self.state_timer = 0.0
        self.cooldown = 0.5
        self.aim_point: tuple[float, float] | None = None
        self.landing_point: tuple[float, float] | None = None

    def on_hurt(self, kind: str) -> None:
        """A hit interrupts any lunge."""
        if self.state in ("aim", "lunge"):
            self._set_state("rest", LUNGE_REST)

    def _set_state(self, state: str, timer: float = 0.0) -> None:
        self.state = state
        self.state_timer = timer

    def start_aim(self, target: tuple[float, float]) -> None:
        """Begin the telegraph, aiming at ``target`` and choosing the off-by-one landing."""
        cx, cy = self.center
        dx, dy = target[0] - cx, target[1] - cy
        side = self.rng.choice((-1, 1))
        if abs(dx) >= abs(dy):
            landing = (target[0], target[1] + side * TILE)
        else:
            landing = (target[0] + side * TILE, target[1])
        self.aim_point = (float(target[0]), float(target[1]))
        self.landing_point = (float(landing[0]), float(landing[1]))
        self._set_state("aim", LUNGE_AIM_TIME)

    def think(self, dt: float, world: Any) -> None:
        """Wander until the player is in range, then telegraph and lunge."""
        self.cooldown = max(0.0, self.cooldown - dt)
        if self.state == "wander":
            player = getattr(world, "player", None)
            if player is not None and self.cooldown <= 0:
                px, py = player.center
                cx, cy = self.center
                if math.hypot(px - cx, py - cy) <= LUNGE_RANGE:
                    self.start_aim((px, py))
                    return
            super().think(dt, world)
        elif self.state == "aim":
            self.bob = -1 if int(self.anim_time / 0.05) % 2 else 0  # jitter telegraph
            self.state_timer -= dt
            if self.state_timer <= 0:
                self._set_state("lunge", LUNGE_MAX_TIME)
        elif self.state == "lunge":
            self.bob = 0
            self._lunge(dt, world)
        elif self.state == "rest":
            self.state_timer -= dt
            if self.state_timer <= 0:
                self.cooldown = LUNGE_COOLDOWN
                self._set_state("wander")

    def _lunge(self, dt: float, world: Any) -> None:
        assert self.landing_point is not None
        cx, cy = self.center
        tx, ty = self.landing_point
        dx, dy = tx - cx, ty - cy
        dist = math.hypot(dx, dy)
        step = LUNGE_SPEED * dt
        self.state_timer -= dt
        if dist <= step:
            hit = self.move(world, dx, dy)
            done = True
        else:
            hit = self.move(world, dx / dist * step, dy / dist * step)
            done = False
        if dx:
            self.flip_x = dx > 0
        if done or hit[0] or hit[1] or self.state_timer <= 0:
            self._set_state("rest", LUNGE_REST)


class Leak(Wanderer):
    """Slime that splits into two half-hp copies every ``SPLIT_TIME`` seconds if ignored.

    Hitting it resets the split timer. A leak with 1 hp cannot split; the world holds at
    most ``MAX_LEAKS`` leaks.
    """

    kind = "leak"

    def __init__(
        self,
        x: float,
        y: float,
        sprite: pygame.Surface | None = None,
        hp: int = 4,
        speed: float = 18.0,
        rng: random.Random | None = None,
        **kw: Any,
    ) -> None:
        super().__init__(x, y, sprite, hp=hp, speed=speed, rng=rng, **kw)
        self.split_timer = SPLIT_TIME

    def on_hurt(self, kind: str) -> None:
        """Attention stops the leak from spreading for a while."""
        self.split_timer = SPLIT_TIME

    def think(self, dt: float, world: Any) -> None:
        """Wander, and split when ignored for too long."""
        super().think(dt, world)
        self.split_timer -= dt
        if self.split_timer <= 0:
            self.split_timer = SPLIT_TIME
            self.split(world)

    def split(self, world: Any) -> Leak | None:
        """Split into two leaks of half hp. Returns the new leak (or None if it can't)."""
        if self.hp < 2:
            return None
        enemies = getattr(world, "enemies", None) or []
        if sum(1 for e in enemies if isinstance(e, Leak) and e.alive) >= MAX_LEAKS:
            return None
        half = self.hp // 2
        self.hp = self.max_hp = half
        child = Leak(
            self.x, self.y, self.sprite, hp=half, speed=self.speed,
            rng=random.Random(self.rng.random()), name=self.name,
            properties=self.properties,
        )
        child.move(world, self.w + 2, 0)
        if child.x == self.x and child.y == self.y:
            child.move(world, -(self.w + 2), 0)
        add_enemy(world, child)
        return child


class Looper(Enemy):
    """Snake that coils back and forth along its row. Takes double damage from cleaves."""

    kind = "looper"

    def __init__(
        self,
        x: float,
        y: float,
        sprite: pygame.Surface | None = None,
        hp: int = 4,
        speed: float = 45.0,
        rng: random.Random | None = None,
        **kw: Any,
    ) -> None:
        super().__init__(x, y, sprite, hp=hp, speed=speed, rng=rng, **kw)
        self.heading = 1

    def damage_multiplier(self, kind: str) -> int:
        """Cleaves (``dd``) cut whole rows: double damage."""
        return 2 if kind == "cleave" else 1

    def think(self, dt: float, world: Any) -> None:
        """Patrol the row, turning at walls; the sprite loops in a small circle."""
        hit_x, _ = self.move(world, self.heading * self.speed * dt, 0)
        if hit_x:
            self.heading = -self.heading
        self.flip_x = self.heading > 0
        self.bob = round(math.sin(self.anim_time * 6.0) * 2)


class NullWisp(Enemy):
    """Phased wisp: only hittable while the player has it locked on (``v``)."""

    kind = "null_wisp"

    def __init__(
        self,
        x: float,
        y: float,
        sprite: pygame.Surface | None = None,
        hp: int = 2,
        speed: float = 25.0,
        rng: random.Random | None = None,
        **kw: Any,
    ) -> None:
        super().__init__(x, y, sprite, hp=hp, speed=speed, rng=rng, **kw)
        self.alpha = WISP_ALPHA

    @property
    def locked(self) -> bool:
        """True while the bound world's ``locked_target`` is this wisp."""
        return getattr(self._world, "locked_target", None) is self

    def can_be_hurt(self, kind: str) -> bool:
        """Phased out unless locked on."""
        return self.locked

    def think(self, dt: float, world: Any) -> None:
        """Drift toward the player when near."""
        self.alpha = 255 if self.locked else WISP_ALPHA
        player = getattr(world, "player", None)
        if player is None:
            return
        px, py = player.center
        cx, cy = self.center
        dx, dy = px - cx, py - cy
        d = math.hypot(dx, dy)
        if 0 < d <= WISP_SIGHT:
            step = self.speed * dt
            self.move(world, dx / d * step, dy / d * step)
            self.flip_x = dx > 0
        self.bob = round(math.sin(self.anim_time * 3.0) * 2)

    def draw(self, surface: pygame.Surface, offset: tuple[int, int]) -> None:
        """Draw at 40% alpha unless locked."""
        self.alpha = 255 if self.locked else WISP_ALPHA
        super().draw(surface, offset)


class StampGolem(Enemy):
    """Immovable, immune door-blocker. It marks its tiles solid until :meth:`dismiss`."""

    kind = "stamp_golem"
    contact_damage = 0
    knockback_enabled = False

    def __init__(
        self,
        x: float,
        y: float,
        sprite: pygame.Surface | None = None,
        hp: int = 1,
        speed: float = 0.0,
        rng: random.Random | None = None,
        **kw: Any,
    ) -> None:
        super().__init__(x, y, sprite, hp=hp, speed=speed, rng=rng, w=16, h=16, **kw)
        self.stamp_flash = 0.0
        self.dismissed = False
        self.blocked_tiles: list[tuple[int, int]] = []

    def hurt(self, damage: int = 1, source: Any = None, kind: str = "strike") -> bool:
        """Immune: show the "stamped" flash and refuse the damage."""
        if self.alive:
            self.stamp_flash = STAMP_FLASH
        return False

    def think(self, dt: float, world: Any) -> None:
        """Stand still; on the first step, make the occupied tiles solid."""
        self.stamp_flash = max(0.0, self.stamp_flash - dt)
        if not self.blocked_tiles:
            grid = world.collision
            ts = grid.tile_size
            x0, y0 = int(self.x // ts), int(self.y // ts)
            x1, y1 = int((self.x + self.w - 1e-6) // ts), int((self.y + self.h - 1e-6) // ts)
            for ty in range(y0, y1 + 1):
                for tx in range(x0, x1 + 1):
                    if not grid.is_solid(tx, ty):
                        grid.set_solid(tx, ty, True)
                        self.blocked_tiles.append((tx, ty))

    def dismiss(self, world: Any) -> None:
        """The greeting rite was performed: free the doorway and leave (no kill event)."""
        for tx, ty in self.blocked_tiles:
            world.collision.set_solid(tx, ty, False)
        self.blocked_tiles = []
        self.dismissed = True
        self._death_reported = True  # leaving is not a kill
        self.alive = False

    def draw(self, surface: pygame.Surface, offset: tuple[int, int]) -> None:
        """Draw, with a red "stamped" frame while flashing."""
        super().draw(surface, offset)
        if self.stamp_flash > 0:
            r = pygame.Rect(
                round(self.x) - offset[0] - 1, round(self.y) - offset[1] - 1,
                int(self.w) + 2, int(self.h) + 2,
            )
            pygame.draw.rect(surface, (220, 40, 40), r, 2)


# ---- factory -----------------------------------------------------------------------------
DUNGEON = "dungeon"
TOWN = "town"

ENEMY_KINDS: dict[str, tuple[type[Enemy], int, str]] = {
    "wanderer": (Wanderer, TILE_RED_SPIDER, DUNGEON),
    "typo_mite": (TypoMite, TILE_RED_SPIDER, DUNGEON),
    "off_by_one": (OffByOne, TILE_BROWN_SPIDER, DUNGEON),
    "leak": (Leak, TILE_GREEN_GHOST, DUNGEON),
    "looper": (Looper, TILE_BAT, DUNGEON),
    "null_wisp": (NullWisp, TILE_GREY_GHOST, DUNGEON),
    "stamp_golem": (StampGolem, TILE_TOWN_GOLEM, TOWN),
}
BOSS_KINDS = ("grubble", "ouroboros", "hollow_archivist")


def _sprite(sprites_module: Any, tile: int | None, sheet: str) -> pygame.Surface | None:
    if sprites_module is None or tile is None:
        return None
    if sheet == TOWN:
        return sprites_module.sheet_tile(tile, sprites_module.TOWN_SHEET)
    return sprites_module.sheet_tile(tile)


def spawn_enemy(obj: Any, sprites_module: Any = None, rng: random.Random | None = None) -> Enemy:
    """Build the enemy described by map object ``obj`` (see the module docstring)."""
    props: dict[str, Any] = dict(obj.properties)
    kind = str(props.get("kind", "wanderer")).strip().lower().replace("-", "_")
    kw: dict[str, Any] = {"rng": rng, "name": obj.name, "properties": props}
    if "hp" in props:
        kw["hp"] = int(props["hp"])
    if "speed" in props:
        kw["speed"] = float(props["speed"])
    if kind in BOSS_KINDS or kind == "archivist":
        from .boss import BOSS_CLASSES, arena_for

        cls, tile, sheet = BOSS_CLASSES["hollow_archivist" if kind == "archivist" else kind]
        kw["arena"] = arena_for(obj)
        kw["minion_sprite"] = _sprite(sprites_module, TILE_RED_SPIDER, DUNGEON)
    else:
        cls, tile, sheet = ENEMY_KINDS.get(kind, ENEMY_KINDS["wanderer"])
    tile_value = props.get("tile", props.get("sprite", tile))
    tile = int(tile_value) if tile_value is not None else None
    sheet = str(props.get("sheet", sheet))
    enemy = cls(0, 0, _sprite(sprites_module, tile, sheet), **kw)
    enemy.place_center(*obj.center)
    return enemy
