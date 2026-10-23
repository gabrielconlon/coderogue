"""NPCs: static characters you talk to.

Spawned from ``npc`` map objects. ``key`` (the object's ``dialogue`` property, falling back
to its lower-cased name) selects lines via ``DialogueBank.pick(key, flags)``. On INTERACT
while the player overlaps :meth:`Npc.interact_box`, the world scene should do::

    npc = self.npc_in_reach()
    if npc is not None:
        dialogue = self.dialogue_bank.pick(npc.key, self.game.progress.flags)
        if dialogue is not None:
            self.held.clear()
            self.game.push(DialogueScene(self.game, dialogue))
"""

from __future__ import annotations

from typing import Any

import pygame

from .base import Entity

INTERACT_REACH = 10  # px the talk zone extends beyond the 16x16 box


class Npc(Entity):
    """A static, solid-looking (but non-blocking) character with a dialogue key."""

    def __init__(
        self,
        x: float,
        y: float,
        sprite: pygame.Surface | None = None,
        name: str = "",
        dialogue_npc_key: str | None = None,
        properties: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(x, y, 16, 16, sprite, name=name, properties=properties)
        key = dialogue_npc_key or self.properties.get("dialogue") or name
        self.key = str(key).strip().lower()

    def interact_box(self) -> tuple[float, float, float, float]:
        """Area in which the player can talk to this NPC."""
        r = INTERACT_REACH
        return (self.x - r, self.y - r, self.w + 2 * r, self.h + 2 * r)
