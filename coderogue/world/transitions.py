"""Map transitions: the fade, the area-title card, map references and door locks.

A *map reference* is how doors, marks and saves name a map: the file stem for maps under
``content/maps`` (``"echo_vale"``), else a path to a ``.tmj`` file.
"""

from __future__ import annotations

from collections.abc import Callable, Collection
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pygame

from coderogue.ui.text import render_text

if TYPE_CHECKING:
    from coderogue.entities.door import Door

FADE_TIME = 0.25  # seconds for each half (out, then in)
AREA_CARD_TIME = 2.0
MAPS_DIR = ("content", "maps")
NULL_DOOR_MESSAGE = "The Null holds this door"


def maps_dir() -> Path:
    """Directory holding the bundled ``.tmj`` maps."""
    from coderogue.app import resource_path

    return resource_path(*MAPS_DIR)


def resolve_map(ref: str | Path) -> Path:
    """Turn a map reference (stem, relative or absolute path) into a ``.tmj`` path."""
    text = str(ref)
    p = Path(text)
    if p.suffix.lower() in (".tmj", ".json") or len(p.parts) > 1:
        if p.exists():
            return p.resolve()
        bundled = maps_dir() / p.name
        if bundled.exists():
            return bundled
        from coderogue.app import resource_path

        return resource_path(text)
    return maps_dir() / f"{text}.tmj"


def map_ref(path: str | Path) -> str:
    """The reference to store for ``path``: its stem if it is a bundled map, else the path."""
    p = Path(path).resolve()
    try:
        if p.parent == maps_dir().resolve() and p.suffix.lower() == ".tmj":
            return p.stem
    except OSError:
        pass
    return str(p)


def door_lock_reason(
    door: Door,
    flags: Collection[str],
    is_solved: Callable[[str], bool],
    pressed_plates: Collection[str],
) -> str:
    """Why ``door`` is locked ("" if it is open).

    ``locked_by`` needs the flag in ``flags``; ``requires_solved`` needs the puzzle solved;
    ``plate`` needs that plate name in ``pressed_plates``.
    """
    if door.locked_by and door.locked_by not in flags:
        return NULL_DOOR_MESSAGE
    if door.requires_solved and not is_solved(door.requires_solved):
        return NULL_DOOR_MESSAGE
    if door.plate and door.plate not in pressed_plates:
        return "The gate is shut. Something heavy might hold the plate down."
    return ""


class Fade:
    """Fade to black, run a callback at full black, fade back in."""

    def __init__(self, duration: float = FADE_TIME) -> None:
        self.duration = duration
        self.phase = "idle"  # "idle" | "out" | "in"
        self.t = 0.0
        self._on_black: Callable[[], Any] | None = None

    @property
    def active(self) -> bool:
        """True while fading out or in."""
        return self.phase != "idle"

    @property
    def alpha(self) -> int:
        """Current black overlay opacity 0..255."""
        if self.phase == "idle":
            return 0
        frac = min(1.0, self.t / self.duration) if self.duration > 0 else 1.0
        return int(255 * (frac if self.phase == "out" else 1.0 - frac))

    def start(self, on_black: Callable[[], Any]) -> bool:
        """Begin fading out; ``on_black`` runs once the screen is black. False if busy."""
        if self.active:
            return False
        self.phase = "out"
        self.t = 0.0
        self._on_black = on_black
        return True

    def update(self, dt: float) -> None:
        """Advance; fires the callback at the out/in boundary."""
        if self.phase == "idle":
            return
        self.t += dt
        if self.t + 1e-9 < self.duration:
            return
        if self.phase == "out":
            callback, self._on_black = self._on_black, None
            self.phase = "in"
            self.t = 0.0
            if callback is not None:
                callback()
        else:
            self.phase = "idle"
            self.t = 0.0

    def draw(self, surface: pygame.Surface) -> None:
        """Darken ``surface`` by the current alpha."""
        a = self.alpha
        if a <= 0:
            return
        veil = pygame.Surface(surface.get_size())
        veil.fill((0, 0, 0))
        veil.set_alpha(a)
        surface.blit(veil, (0, 0))


class AreaCard:
    """Big area-name text shown for a couple of seconds after entering a map."""

    def __init__(self) -> None:
        self.text = ""
        self.time = 0.0

    def show(self, text: str, seconds: float = AREA_CARD_TIME) -> None:
        """Start showing ``text``."""
        self.text = text
        self.time = seconds

    @property
    def visible(self) -> bool:
        """True while the card is up."""
        return self.time > 0 and bool(self.text)

    def update(self, dt: float) -> None:
        """Count down."""
        self.time = max(0.0, self.time - dt)

    def draw(self, surface: pygame.Surface) -> None:
        """Centred title with a fade-out over the last half second."""
        if not self.visible:
            return
        alpha = int(255 * min(1.0, self.time / 0.5))
        title = render_text(self.text, 40, (240, 200, 110), bold=True)
        shadow = render_text(self.text, 40, (0, 0, 0), bold=True)
        title.set_alpha(alpha)
        shadow.set_alpha(alpha)
        sw, sh = surface.get_size()
        x = (sw - title.get_width()) // 2
        y = sh // 3 - title.get_height() // 2
        surface.blit(shadow, (x + 2, y + 2))
        surface.blit(title, (x, y))
