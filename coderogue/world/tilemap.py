"""Renderable tile map built from :class:`~coderogue.world.loader.MapData`."""

from __future__ import annotations

from pathlib import Path

import pygame

from coderogue.world.collision import CollisionGrid
from coderogue.world.loader import MapData, load_map

GROUND_LAYER = "ground"
WALLS_LAYER = "walls"
DECOR_LAYER = "decor"
ABOVE_LAYER = "above"

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
        self.collision = CollisionGrid(self.width, self.height, self.tile_size, solid)
        self.below = self._render_layers([n for n in data.layer_order if n != ABOVE_LAYER])
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

    def draw_below(self, target: pygame.Surface, offset: tuple[int, int]) -> None:
        """Draw every layer except ``above`` (everything under entities)."""
        target.blit(self.below, (-offset[0], -offset[1]))

    def draw_above(self, target: pygame.Surface, offset: tuple[int, int]) -> None:
        """Draw the ``above`` layer over entities, if present."""
        if self.above is not None:
            target.blit(self.above, (-offset[0], -offset[1]))
