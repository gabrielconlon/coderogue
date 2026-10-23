"""Combat resolution between the player and ``world.enemies`` (scene-agnostic helpers).

``world`` is anything with ``player``, ``enemies`` and ``collision``; optional hooks are
``locked_target``, ``spawn_enemy_instance(enemy)`` and ``on_enemy_killed(enemy)``.
Typical fixed step in a scene::

    combat.update_enemies(self, dt)  # enemy AI + contact damage
    box = player.attack_box()
    if box is not None:
        combat.resolve_player_attacks(self, box, 1, "strike", struck=player.struck)
    combat.reap(self)  # drop the dead, emitting on_enemy_killed once each
"""

from __future__ import annotations

from typing import Any

from coderogue.world.collision import boxes_overlap

Box = tuple[float, float, float, float]


def _hazards(enemy: Any) -> list[tuple[Any, int]]:
    hazards = getattr(enemy, "hazards", None)
    if callable(hazards):
        return list(hazards())
    damage = getattr(enemy, "contact_damage", 1)
    return [(enemy, damage)] if enemy.alive and damage > 0 else []


def _targets(enemy: Any) -> list[Any]:
    targets = getattr(enemy, "targets", None)
    if callable(targets):
        return list(targets())
    return [enemy] if enemy.alive else []


def update_enemies(world: Any, dt: float) -> None:
    """Update every enemy (including ones added mid-loop) then resolve contact damage."""
    enemies = world.enemies
    i = 0
    while i < len(enemies):
        enemy = enemies[i]
        if enemy.alive:
            enemy.update(dt, world)
        i += 1
    resolve_contacts(world)


def resolve_contacts(world: Any) -> int:
    """Hurt the player for each enemy hazard it overlaps (player i-frames apply).

    Returns the number of hits that landed. A hazard with an ``on_hit()`` method (boss
    cards) is told when it lands.
    """
    player = getattr(world, "player", None)
    if player is None:
        return 0
    landed = 0
    for enemy in list(world.enemies):
        if not enemy.alive:
            continue
        for hazard, damage in _hazards(enemy):
            if damage <= 0 or not getattr(hazard, "alive", True):
                continue
            if boxes_overlap(player.box, hazard.box) and player.hurt(damage, hazard.center):
                landed += 1
                on_hit = getattr(hazard, "on_hit", None)
                if callable(on_hit):
                    on_hit()
    return landed


def resolve_player_attacks(
    world: Any,
    hitbox: Box,
    dmg: int = 1,
    kind: str = "strike",
    struck: set[int] | None = None,
) -> list[Any]:
    """Apply a player attack ``hitbox`` to every enemy target it overlaps.

    ``struck`` (e.g. ``player.struck``) holds ``id()``s already hit by this swing and is
    updated, so a lingering hitbox hits each target once. Returns the targets damaged.
    """
    player = getattr(world, "player", None)
    hit: list[Any] = []
    for enemy in list(world.enemies):
        if not enemy.alive:
            continue
        bind = getattr(enemy, "bind", None)
        if callable(bind):
            bind(world)
        for target in _targets(enemy):
            key = id(target)
            if struck is not None and key in struck:
                continue
            if not boxes_overlap(hitbox, target.box):
                continue
            if struck is not None:
                struck.add(key)
            if target.hurt(dmg, player, kind=kind):
                hit.append(target)
    return hit


def reap(world: Any) -> list[Any]:
    """Remove dead enemies from ``world.enemies`` in place, reporting each death once."""
    dead = [e for e in world.enemies if not e.alive]
    for enemy in dead:
        report = getattr(enemy, "report_death", None)
        if callable(report):
            report(world)
    world.enemies[:] = [e for e in world.enemies if e.alive]
    return dead
