"""Bosses: Grubble the Typo King (Ch1), the Ouroboros (Ch2), the Hollow Archivist (Ch3 stub).

Shared contract with the world scene:

* A boss lives in ``world.enemies`` like any bug; :mod:`coderogue.entities.combat` hits its
  child entities through :meth:`Boss.targets` and is hurt by them through
  :meth:`Boss.hazards`.
* ``boss.open_lectern(index)`` is True while lectern/loop-stone ``index`` may be used (the
  world opens the altar for that boss phase then). When the phase's puzzle is solved the
  world calls ``boss.phase_solved(index)``. After ``phase_count`` solves the boss deflates:
  ``dying`` is True for ``DEFLATE_TIME`` seconds, then it dies (``on_enemy_killed`` fires).
* Bosses never take hp damage from attacks: the puzzles are the kill.
"""

from __future__ import annotations

import math
import random
from typing import Any

import pygame

from .base import Entity
from .enemies import (
    TILE,
    TILE_BAT,
    TILE_GREY_GHOST,
    TILE_RED_SPIDER,
    Enemy,
    TypoMite,
    add_enemy,
)

DEFLATE_TIME = 1.5

# Grubble
GRUBBLE_TELEGRAPH = 0.5
GRUBBLE_CHARGE_SPEED = 200.0
GRUBBLE_CHARGE_MAX = 1.5
GRUBBLE_RECOVER = 0.7
GRUBBLE_CHARGE_COOLDOWN = 2.0
GRUBBLE_SPAWN_INTERVAL = 8.0
GRUBBLE_SPAWN_COUNT = 2
GRUBBLE_MAX_MITES = 6
GRUBBLE_STUN = 6.0
CROWN_LETTERS = "TPY"
LETTER_COOLDOWN = 0.3  # one letter per strike

# Ouroboros
OURO_SEGMENTS = 8
OURO_SPACING = 0.32  # radians between segments
OURO_GLOW_INTERVAL = 5.0

# Hollow Archivist
ARCHIVIST_TELEPORT = 3.0
ARCHIVIST_HITS_TO_EXPOSE = 3
ARCHIVIST_STUN = 6.0
CARD_SPEED = 110.0
CARD_LIFETIME = 4.0


def arena_for(obj: Any) -> pygame.Rect:
    """Arena rect for a boss map object: its own rect if it is a region, else a default room.

    ``arena_w``/``arena_h`` properties (in tiles) override the default 12x9-tile size.
    """
    props = getattr(obj, "properties", {}) or {}
    if obj.width > TILE and obj.height > TILE:
        return pygame.Rect(round(obj.x), round(obj.y), round(obj.width), round(obj.height))
    w = int(props.get("arena_w", 12)) * TILE
    h = int(props.get("arena_h", 9)) * TILE
    cx, cy = obj.center
    return pygame.Rect(round(cx - w / 2), round(cy - h / 2), w, h)


class Boss(Enemy):
    """Base boss: phases, an ``arena`` rect, a ``stunned`` timer and the deflate death."""

    kind = "boss"
    phase_count = 3
    knockback_enabled = False

    def __init__(
        self,
        x: float,
        y: float,
        sprite: pygame.Surface | None = None,
        hp: int = 99,
        speed: float = 25.0,
        rng: random.Random | None = None,
        arena: pygame.Rect | tuple[int, int, int, int] | None = None,
        minion_sprite: pygame.Surface | None = None,
        w: float = 14,
        h: float = 12,
        **kw: Any,
    ) -> None:
        super().__init__(x, y, sprite, hp=hp, speed=speed, rng=rng, w=w, h=h, **kw)
        if arena is None:
            arena = (round(x) - 6 * TILE, round(y) - 4 * TILE, 12 * TILE, 9 * TILE)
        self.arena = pygame.Rect(arena)
        self.minion_sprite = minion_sprite
        self.solved: set[int] = set()
        self.stun_timer = 0.0
        self.dying = False
        self.death_timer = 0.0

    # ---- phases ----------------------------------------------------------------------
    @property
    def stunned(self) -> bool:
        """True while the stun timer runs."""
        return self.stun_timer > 0

    def stun(self, seconds: float) -> None:
        """Stun for ``seconds``."""
        self.stun_timer = max(self.stun_timer, seconds)

    def next_unsolved(self) -> int | None:
        """Lowest phase index not yet solved."""
        return next((i for i in range(self.phase_count) if i not in self.solved), None)

    def open_lectern(self, index: int) -> bool:
        """True while lectern ``index`` may be used (default: stunned and it is next)."""
        return self.stunned and not self.dying and index == self.next_unsolved()

    def phase_solved(self, index: int) -> None:
        """The world solved phase ``index``; deflate after the last."""
        self.solved.add(index)
        if len(self.solved) >= self.phase_count and not self.dying:
            self.deflate()

    def deflate(self) -> None:
        """Start the death animation (``DEFLATE_TIME`` seconds)."""
        self.dying = True
        self.death_timer = DEFLATE_TIME
        self.stun_timer = 0.0

    # ---- combat ----------------------------------------------------------------------
    def can_be_hurt(self, kind: str) -> bool:
        """Bosses are not worn down by hp damage."""
        return False

    def hazards(self) -> list[tuple[Entity, int]]:
        """Harmless while stunned or deflating."""
        if self.dying or self.stunned:
            return []
        return super().hazards()

    def children(self) -> list[Entity]:
        """Owned child entities (letters, segments, cards), updated and drawn by the boss."""
        return []

    def targets(self) -> list[Entity]:
        """The boss and its live children."""
        if not self.alive or self.dying:
            return []
        return [self, *[c for c in self.children() if c.alive]]

    # ---- simulation ------------------------------------------------------------------
    def update(self, dt: float, world: Any) -> None:
        """Run the death animation, the stun timer, or the boss's :meth:`think`."""
        self._world = world
        self.iframes = max(0.0, self.iframes - dt)
        self.anim_time += dt
        if self.dying:
            self.death_timer -= dt
            if self.death_timer <= 1e-9:
                self.death_timer = 0.0
                self.die()
            return
        if self.stun_timer > 0:
            self.stun_timer -= dt
            if self.stun_timer <= 1e-9:
                self.stun_timer = 0.0
                self.on_stun_end()
            else:
                self.think_stunned(dt, world)
                return
        self.think(dt, world)

    def think_stunned(self, dt: float, world: Any) -> None:
        """Per-step behaviour while stunned (default: nothing)."""

    def on_stun_end(self) -> None:
        """Hook: the stun wore off."""

    def clamp_to_arena(self) -> bool:
        """Keep the hitbox inside ``arena``; True if it had to be pushed back."""
        a = self.arena
        nx = min(max(self.x, a.left), a.right - self.w)
        ny = min(max(self.y, a.top), a.bottom - self.h)
        moved = (nx, ny) != (self.x, self.y)
        self.x, self.y = nx, ny
        return moved

    def spawn_minion(self, world: Any, offset: tuple[float, float]) -> TypoMite:
        """Spawn a Typo-mite at ``offset`` from the boss centre (clamped to the arena)."""
        mite = TypoMite(0, 0, self.minion_sprite, rng=random.Random(self.rng.random()))
        cx, cy = self.center
        a = self.arena
        mx = min(max(cx + offset[0], a.left + mite.w), a.right - mite.w)
        my = min(max(cy + offset[1], a.top + mite.h), a.bottom - mite.h)
        mite.place_center(mx, my)
        mite.spawned_by = self
        add_enemy(world, mite)
        return mite

    # ---- drawing ---------------------------------------------------------------------
    def draw(self, surface: pygame.Surface, offset: tuple[int, int]) -> None:
        """Draw the boss (shrinking while deflating, blinking while stunned) and children."""
        if self.dying and self.sprite is not None:
            scale = max(0.05, self.death_timer / DEFLATE_TIME)
            sw, sh = self.sprite.get_size()
            small = pygame.transform.scale(
                self.sprite, (max(1, round(sw * scale)), max(1, round(sh * scale)))
            )
            cx = round(self.x + self.w / 2 - small.get_width() / 2) - offset[0]
            cy = round(self.y + self.h - small.get_height()) - offset[1]
            surface.blit(small, (cx, cy))
        elif not (self.stunned and int(self.anim_time * 8) % 2):
            super().draw(surface, offset)
        for child in self.children():
            if child.alive:
                child.draw(surface, offset)


# ---- Grubble ------------------------------------------------------------------------------
class CrownLetter(Entity):
    """One glowing misspelled letter orbiting above Grubble. A strike knocks it off."""

    def __init__(self, boss: Grubble, index: int, letter: str) -> None:
        super().__init__(0, 0, 6, 6, None, name=f"crown-{letter}")
        self.boss = boss
        self.index = index
        self.letter = letter
        self.struck = False

    def hurt(self, damage: int = 1, source: Any = None, kind: str = "strike") -> bool:
        """Any hit knocks the letter off (while Grubble is not already stunned)."""
        boss = self.boss
        if self.struck or boss.stunned or boss.dying or boss.letter_cooldown > 0:
            return False
        self.struck = True
        boss.letter_cooldown = LETTER_COOLDOWN
        self.boss.on_letter_struck(self)
        return True

    def place(self, angle: float) -> None:
        """Orbit position around the top of the boss."""
        cx, cy = self.boss.center
        self.place_center(cx + math.cos(angle) * 10, cy - 8 + math.sin(angle) * 3)

    def draw(self, surface: pygame.Surface, offset: tuple[int, int]) -> None:
        """A small gold square (dim once struck)."""
        color = (90, 80, 60) if self.struck else (255, 214, 90)
        r = pygame.Rect(round(self.x) - offset[0], round(self.y) - offset[1], 6, 6)
        pygame.draw.rect(surface, color, r)


class Grubble(Boss):
    """Grubble, the Typo King.

    States: ``idle`` (walks toward the player) -> ``telegraph`` (``GRUBBLE_TELEGRAPH`` s,
    facing ``charge_dir``) -> ``charge`` (straight line along the player's row/column until a
    wall, the arena edge or ``GRUBBLE_CHARGE_MAX``) -> ``recover``. Every
    ``GRUBBLE_SPAWN_INTERVAL`` s he spawns 2 Typo-mites (max 6 of his alive). Striking all 3
    crown letters stuns him for ``GRUBBLE_STUN`` s and opens the next lectern.
    """

    kind = "grubble"

    def __init__(self, x: float, y: float, sprite: pygame.Surface | None = None, **kw: Any) -> None:
        kw.setdefault("w", 16)
        kw.setdefault("h", 14)
        super().__init__(x, y, sprite, **kw)
        self.state = "idle"
        self.state_timer = 0.0
        self.charge_cooldown = GRUBBLE_CHARGE_COOLDOWN
        self.charge_dir: tuple[int, int] = (0, 0)
        self.spawn_timer = GRUBBLE_SPAWN_INTERVAL
        self.letter_cooldown = 0.0
        self.letters = [CrownLetter(self, i, ch) for i, ch in enumerate(CROWN_LETTERS)]
        self._place_letters()

    def children(self) -> list[Entity]:
        """The crown letters still on his head."""
        return [c for c in self.letters if not c.struck]

    def _place_letters(self) -> None:
        n = len(self.letters)
        for letter in self.letters:
            letter.place(self.anim_time * 2.0 + letter.index * 2 * math.pi / n)

    def on_letter_struck(self, letter: CrownLetter) -> None:
        """All letters struck: stunned, and the next lectern opens."""
        if all(c.struck for c in self.letters):
            self.stun(GRUBBLE_STUN)
            self.state = "idle"
            self.state_timer = 0.0

    def on_stun_end(self) -> None:
        """The crown regrows."""
        for c in self.letters:
            c.struck = False
        self.charge_cooldown = GRUBBLE_CHARGE_COOLDOWN

    def alive_minions(self, world: Any) -> int:
        """How many of his Typo-mites are alive."""
        enemies = getattr(world, "enemies", None) or []
        return sum(1 for e in enemies if getattr(e, "spawned_by", None) is self and e.alive)

    def _spawn_wave(self, world: Any) -> None:
        room = GRUBBLE_MAX_MITES - self.alive_minions(world)
        for i in range(min(GRUBBLE_SPAWN_COUNT, room)):
            side = -1 if i % 2 == 0 else 1
            self.spawn_minion(world, (side * 1.5 * TILE, TILE))

    def start_telegraph(self, player_center: tuple[float, float]) -> None:
        """Pick the axis toward the player's row/column and start the wind-up."""
        cx, cy = self.center
        dx, dy = player_center[0] - cx, player_center[1] - cy
        if abs(dx) >= abs(dy):
            self.charge_dir = (1 if dx >= 0 else -1, 0)
        else:
            self.charge_dir = (0, 1 if dy >= 0 else -1)
        self.state = "telegraph"
        self.state_timer = GRUBBLE_TELEGRAPH

    def think(self, dt: float, world: Any) -> None:
        """Charge pattern plus mite waves."""
        self.letter_cooldown = max(0.0, self.letter_cooldown - dt)
        self._place_letters()
        self.spawn_timer -= dt
        if self.spawn_timer <= 0:
            self.spawn_timer += GRUBBLE_SPAWN_INTERVAL
            self._spawn_wave(world)
        player = getattr(world, "player", None)
        if self.state == "idle":
            self.charge_cooldown -= dt
            if player is None:
                return
            if self.charge_cooldown <= 0:
                self.start_telegraph(player.center)
                return
            px, py = player.center
            cx, cy = self.center
            d = math.hypot(px - cx, py - cy)
            if d > TILE:
                step = self.speed * dt
                self.move(world, (px - cx) / d * step, (py - cy) / d * step)
                self.clamp_to_arena()
        elif self.state == "telegraph":
            self.bob = -1 if int(self.anim_time / 0.05) % 2 else 0
            self.state_timer -= dt
            if self.state_timer <= 1e-9:
                self.bob = 0
                self.state = "charge"
                self.state_timer = GRUBBLE_CHARGE_MAX
        elif self.state == "charge":
            step = GRUBBLE_CHARGE_SPEED * dt
            hit_x, hit_y = self.move(world, self.charge_dir[0] * step, self.charge_dir[1] * step)
            edge = self.clamp_to_arena()
            self.state_timer -= dt
            if hit_x or hit_y or edge or self.state_timer <= 0:
                self.state = "recover"
                self.state_timer = GRUBBLE_RECOVER
        elif self.state == "recover":
            self.state_timer -= dt
            if self.state_timer <= 0:
                self.state = "idle"
                self.charge_cooldown = GRUBBLE_CHARGE_COOLDOWN
        self._place_letters()

    def think_stunned(self, dt: float, world: Any) -> None:
        """Dazed: mites keep coming but he stays put."""
        self.spawn_timer -= dt
        if self.spawn_timer <= 0:
            self.spawn_timer += GRUBBLE_SPAWN_INTERVAL
            self._spawn_wave(world)

    def draw(self, surface: pygame.Surface, offset: tuple[int, int]) -> None:
        """Draw, with a charge-line telegraph."""
        if self.state == "telegraph" and not self.dying:
            cx, cy = self.center
            ex = cx + self.charge_dir[0] * 4 * TILE
            ey = cy + self.charge_dir[1] * 4 * TILE
            pygame.draw.line(
                surface, (255, 80, 60),
                (round(cx) - offset[0], round(cy) - offset[1]),
                (round(ex) - offset[0], round(ey) - offset[1]),
            )
        super().draw(surface, offset)


# ---- Ouroboros ----------------------------------------------------------------------------
class Segment(Entity):
    """One body segment of the Ouroboros. Any hit severs it; it regrows each lap."""

    def __init__(self, boss: Ouroboros, index: int) -> None:
        super().__init__(0, 0, 10, 10, None, name=f"segment-{index}")
        self.boss = boss
        self.index = index
        self.severed = False
        self.glowing = False

    @property
    def alive_segment(self) -> bool:
        """Present on the body."""
        return not self.severed

    def hurt(self, damage: int = 1, source: Any = None, kind: str = "strike") -> bool:
        """Sever the segment; cleaving the glowing one opens the next loop-stone."""
        if self.severed or self.boss.dying:
            return False
        was_glowing = self.glowing
        self.severed = True
        self.glowing = False
        if was_glowing and kind == "cleave":
            self.boss.on_glow_cleaved(self)
        return True

    def draw(self, surface: pygame.Surface, offset: tuple[int, int]) -> None:
        """Body circle (bright when glowing)."""
        if self.severed:
            return
        color = (255, 240, 120) if self.glowing else (120, 170, 90)
        cx, cy = self.center
        pygame.draw.circle(surface, color, (round(cx) - offset[0], round(cy) - offset[1]), 5)


class Ouroboros(Boss):
    """The worm that eats its tail: a head plus ``OURO_SEGMENTS`` segments on a circle.

    The head runs around the arena centre at ``speed`` px/s; each full lap regrows severed
    segments unless 3 phases are solved. Every ``OURO_GLOW_INTERVAL`` s the next intact
    segment glows (lockable with ``v``); cleaving it opens loop-stone ``next_unsolved()``.
    """

    kind = "ouroboros"

    def __init__(self, x: float, y: float, sprite: pygame.Surface | None = None, **kw: Any) -> None:
        radius = kw.pop("radius", None)
        kw.setdefault("speed", 50.0)
        super().__init__(x, y, sprite, w=12, h=12, **kw)
        cx, cy = self.arena.center
        self.ring_center = (float(cx), float(cy))
        self.radius = float(radius or max(TILE, min(self.arena.w, self.arena.h) / 2 - TILE))
        self.head_angle = 0.0
        self.lap_progress = 0.0
        self.laps = 0
        self.segments = [Segment(self, i) for i in range(OURO_SEGMENTS)]
        self.glow_timer = OURO_GLOW_INTERVAL
        self.glow_index = -1
        self.open_stone: int | None = None
        self._place_body()

    def children(self) -> list[Entity]:
        """Intact segments."""
        return [s for s in self.segments if not s.severed]

    def _point(self, angle: float) -> tuple[float, float]:
        cx, cy = self.ring_center
        return (cx + math.cos(angle) * self.radius, cy + math.sin(angle) * self.radius)

    def _place_body(self) -> None:
        self.place_center(*self._point(self.head_angle))
        for s in self.segments:
            s.place_center(*self._point(self.head_angle - (s.index + 1) * OURO_SPACING))

    def open_lectern(self, index: int) -> bool:
        """Loop-stone ``index`` is open after its glowing segment was cleaved."""
        return not self.dying and self.open_stone == index and index not in self.solved

    open_loop_stone = open_lectern

    def phase_solved(self, index: int) -> None:
        """Close the stone and record the phase."""
        if self.open_stone == index:
            self.open_stone = None
        super().phase_solved(index)

    def on_glow_cleaved(self, segment: Segment) -> None:
        """The glowing segment was cleaved: open the next loop-stone."""
        self.open_stone = self.next_unsolved()

    def glow_next(self) -> Segment | None:
        """Move the glow to the next intact segment (cycling)."""
        for s in self.segments:
            s.glowing = False
        n = len(self.segments)
        for step in range(1, n + 1):
            i = (self.glow_index + step) % n
            if not self.segments[i].severed:
                self.glow_index = i
                self.segments[i].glowing = True
                return self.segments[i]
        return None

    def regrow(self) -> None:
        """Every severed segment grows back."""
        for s in self.segments:
            s.severed = False

    def think(self, dt: float, world: Any) -> None:
        """Circle the ring, regrow on each lap, cycle the glow."""
        omega = self.speed / self.radius
        self.head_angle += omega * dt
        self.lap_progress += omega * dt
        while self.lap_progress >= 2 * math.pi:
            self.lap_progress -= 2 * math.pi
            self.laps += 1
            if len(self.solved) < 3:
                self.regrow()
        self.glow_timer -= dt
        if self.glow_timer <= 1e-9:
            self.glow_timer += OURO_GLOW_INTERVAL
            self.glow_next()
        self._place_body()
        self.flip_x = math.sin(self.head_angle) < 0

    def hazards(self) -> list[tuple[Entity, int]]:
        """Head and intact segments bite."""
        if self.dying or not self.alive:
            return []
        return [(self, self.contact_damage), *[(s, 1) for s in self.children()]]


# ---- Hollow Archivist ----------------------------------------------------------------------
class Card(Entity):
    """A thrown index card: flies straight, vanishes on a wall, after a while, or on a hit."""

    def __init__(self, x: float, y: float, vx: float, vy: float) -> None:
        super().__init__(x, y, 6, 6, None, name="card")
        self.vx = vx
        self.vy = vy
        self.life = CARD_LIFETIME

    def on_hit(self) -> None:
        """It hit the player."""
        self.alive = False

    def update(self, dt: float, world: Any) -> None:
        """Fly; despawn when the next position is inside a wall."""
        self.life -= dt
        nx, ny = self.x + self.vx * dt, self.y + self.vy * dt
        if self.life <= 0 or world.collision.box_hits(nx, ny, self.w, self.h):
            self.alive = False
            return
        self.x, self.y = nx, ny

    def draw(self, surface: pygame.Surface, offset: tuple[int, int]) -> None:
        """A small cream rectangle."""
        r = pygame.Rect(round(self.x) - offset[0], round(self.y) - offset[1], 6, 4)
        pygame.draw.rect(surface, (240, 230, 200), r)


class HollowArchivist(Boss):
    """Stub: teleports between 4 points every 3 s and throws a card at the player.

    Stand-in for the ``yy``/``p`` shield mechanic: ``ARCHIVIST_HITS_TO_EXPOSE`` strikes stun
    it (exposed) for ``ARCHIVIST_STUN`` s, which opens the next lectern.
    """

    kind = "hollow_archivist"
    phase_count = 4  # 3-B has four phases (a-d), one lectern each

    def __init__(self, x: float, y: float, sprite: pygame.Surface | None = None, **kw: Any) -> None:
        points = kw.pop("points", None)
        super().__init__(x, y, sprite, **kw)
        a = self.arena.inflate(-4 * TILE, -4 * TILE)
        self.points: list[tuple[float, float]] = list(
            points or [a.topleft, a.topright, a.bottomright, a.bottomleft]
        )
        self.point_index = -1
        self.teleport_timer = ARCHIVIST_TELEPORT
        self.cards: list[Card] = []
        self.hits = 0

    def children(self) -> list[Entity]:
        """Cards in flight."""
        return list(self.cards)

    def targets(self) -> list[Entity]:
        """Only the Archivist itself can be struck."""
        return [self] if self.alive and not self.dying else []

    def hurt(self, damage: int = 1, source: Any = None, kind: str = "strike") -> bool:
        """Count a hit toward exposing it (no hp damage)."""
        if not self.alive or self.dying or self.stunned or self.iframes > 0:
            return False
        self.iframes = 0.25
        self.hits += 1
        if self.hits >= ARCHIVIST_HITS_TO_EXPOSE:
            self.hits = 0
            self.stun(ARCHIVIST_STUN)
        return True

    def teleport(self, world: Any) -> Card | None:
        """Jump to the next point and throw a card at the player."""
        self.point_index = (self.point_index + 1) % len(self.points)
        self.place_center(*self.points[self.point_index])
        player = getattr(world, "player", None)
        if player is None:
            return None
        cx, cy = self.center
        px, py = player.center
        d = math.hypot(px - cx, py - cy) or 1.0
        card = Card(cx - 3, cy - 3, (px - cx) / d * CARD_SPEED, (py - cy) / d * CARD_SPEED)
        self.cards.append(card)
        return card

    def _tick_cards(self, dt: float, world: Any) -> None:
        for card in self.cards:
            card.update(dt, world)
        self.cards = [c for c in self.cards if c.alive]

    def think(self, dt: float, world: Any) -> None:
        """Teleport on a fixed rhythm; cards fly."""
        self.teleport_timer -= dt
        if self.teleport_timer <= 1e-9:
            self.teleport_timer += ARCHIVIST_TELEPORT
            self.teleport(world)
        self._tick_cards(dt, world)

    def think_stunned(self, dt: float, world: Any) -> None:
        """Exposed: cards already thrown keep flying."""
        self._tick_cards(dt, world)

    def hazards(self) -> list[tuple[Entity, int]]:
        """The Archivist and its cards."""
        if self.dying or not self.alive:
            return []
        own = [] if self.stunned else [(self, self.contact_damage)]
        return [*own, *[(c, 1) for c in self.cards if c.alive]]


BOSS_CLASSES: dict[str, tuple[type[Boss], int, str]] = {
    "grubble": (Grubble, TILE_RED_SPIDER, "dungeon"),
    "ouroboros": (Ouroboros, TILE_BAT, "dungeon"),
    "hollow_archivist": (HollowArchivist, TILE_GREY_GHOST, "dungeon"),
}
