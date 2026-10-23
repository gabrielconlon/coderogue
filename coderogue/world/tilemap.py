"""Renderable tile map built from :class:`~coderogue.world.loader.MapData`."""

from __future__ import annotations

import time
from pathlib import Path

import pygame

from coderogue.world.collision import CollisionGrid
from coderogue.world.loader import WATER_LAYER, MapData, load_map

GROUND_LAYER = "ground"
WALLS_LAYER = "walls"
DECOR_LAYER = "decor"
ABOVE_LAYER = "above"

WATER_TINT = (40, 110, 170, 120)  # translucent blue-teal wash over water cells
WATER_HIGHLIGHT = (150, 205, 230, 150)  # the 1 px ripple row
WATER_FRAME_TIME = 0.6  # seconds per ripple frame (two frames)

_image_cache: dict[Path, pygame.Surface] = {}


def load_image(path: Path) -> pygame.Surface:
    """Load (and cache) an image, converting for fast blits when a display exists."""
    path = Path(path).resolve()
    surf = _image_cache.get(path)
    if surf is None:
        surf = pygame.image.load(str(path))
        if pygame.display.get_init() and pygame.display.get_surface() is not None:
            surf = surf.convert_alpha()
        _image_cache[path] = surf
    return surf


class TileMap:
    """Tile layers pre-rendered to surfaces plus a collision grid from the ``walls`` layer.

    Layers draw in Tiled order under entities (``ground``, ``walls``, ``decor``, ...), except
    a layer named ``above`` which draws over entities (archways, tree canopies).

    Water cells (:attr:`MapData.water`) are solid and get a translucent tint after the
    ground/walls/water layers (before ``decor``). The tint ripples between two frames; both
    are baked into pre-rendered ``below`` surfaces, so drawing costs one blit either way.
    """

    def __init__(self, data: MapData) -> None:
        self.data = data
        self.tile_size = data.tilewidth
        self.width = data.width
        self.height = data.height
        self.pixel_width, self.pixel_height = data.pixel_size
        self._tiles: dict[int, pygame.Surface] = {}
        walls = data.layers.get(WALLS_LAYER)
        solid = [bool(g) for g in walls.data] if walls else [False] * (self.width * self.height)
        self.water: set[tuple[int, int]] = {
            (tx, ty) for tx, ty in data.water if 0 <= tx < self.width and 0 <= ty < self.height
        }
        for tx, ty in self.water:
            solid[ty * self.width + tx] = True
        self.collision = CollisionGrid(self.width, self.height, self.tile_size, solid)
        self.below_frames = self._render_below()
        self.below = self.below_frames[0]
        self.above = (
            self._render_layers([ABOVE_LAYER]) if ABOVE_LAYER in data.layers else None
        )

    @classmethod
    def load(cls, path: str | Path) -> TileMap:
        """Load a ``.tmj`` file and build the map."""
        return cls(load_map(path))

    def tile_surface(self, gid: int) -> pygame.Surface | None:
        """The 16x16 surface for a gid (cached), or None for empty/unknown gids."""
        if gid in self._tiles:
            return self._tiles[gid]
        ts = self.data.tileset_for(gid)
        if ts is None:
            return None
        sheet = load_image(ts.image)
        surf = sheet.subsurface(pygame.Rect(ts.source_rect(gid - ts.firstgid))).copy()
        self._tiles[gid] = surf
        return surf

    def _render_layers(self, names: list[str]) -> pygame.Surface:
        surf = pygame.Surface((self.pixel_width, self.pixel_height), pygame.SRCALPHA)
        ts = self.tile_size
        for name in names:
            layer = self.data.layers.get(name)
            if layer is None or not layer.visible:
                continue
            for ty in range(layer.height):
                for tx in range(layer.width):
                    gid = layer.data[ty * layer.width + tx]
                    if gid:
                        tile = self.tile_surface(gid)
                        if tile is not None:
                            surf.blit(tile, (tx * ts, ty * ts))
        return surf

    def _render_below(self) -> tuple[pygame.Surface, ...]:
        """The under-entity layers, once per ripple frame (one surface without water)."""
        names = [n for n in self.data.layer_order if n != ABOVE_LAYER]
        if not self.water:
            return (self._render_layers(names),)
        split = 0  # the tint goes over ground/walls/water, under decor and the rest
        for i, name in enumerate(names):
            if name in (GROUND_LAYER, WALLS_LAYER, WATER_LAYER) or (
                self.data.layers[name].properties.get(WATER_LAYER)
            ):
                split = i + 1
        base = self._render_layers(names[:split])
        rest = self._render_layers(names[split:])
        frames = []
        for frame in range(2):
            surf = base.copy()
            surf.blit(self._water_overlay(frame), (0, 0))
            surf.blit(rest, (0, 0))
            frames.append(surf)
        return tuple(frames)

    def _water_overlay(self, frame: int) -> pygame.Surface:
        """Tint plus a short 1 px highlight per water cell; the highlight row moves per frame."""
        ts = self.tile_size
        overlay = pygame.Surface((self.pixel_width, self.pixel_height), pygame.SRCALPHA)
        for tx, ty in self.water:
            x, y = tx * ts, ty * ts
            overlay.fill(WATER_TINT, (x, y, ts, ts))
            phase = (tx + ty + frame) % 2  # checkerboard so the surface shimmers
            hx = x + (2 if phase == 0 else ts // 2 - 1)
            hy = y + (ts // 4 if phase == 0 else (ts * 5) // 8)
            overlay.fill(WATER_HIGHLIGHT, (hx, hy, ts // 2 - 1, 1))
        return overlay

    def water_frame(self, now: float | None = None) -> int:
        """Index of the ripple frame to show at time ``now`` (seconds; default: monotonic)."""
        if len(self.below_frames) < 2:
            return 0
        t = time.monotonic() if now is None else now
        return int(t / WATER_FRAME_TIME) % 2

    def draw_below(
        self, target: pygame.Surface, offset: tuple[int, int], now: float | None = None
    ) -> None:
        """Draw every layer except ``above`` (everything under entities), water tinted."""
        surf = self.below_frames[self.water_frame(now)]
        target.blit(surf, (-offset[0], -offset[1]))

    def draw_above(self, target: pygame.Surface, offset: tuple[int, int]) -> None:
        """Draw the ``above`` layer over entities, if present."""
        if self.above is not None:
            target.blit(self.above, (-offset[0], -offset[1]))
