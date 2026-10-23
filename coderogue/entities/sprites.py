"""Sprite lookup helpers for the Kenney 16x16 sheets."""

from __future__ import annotations

from pathlib import Path

import pygame

TILE = 16
SHEET_COLUMNS = 12
DUNGEON_SHEET = ("assets", "kenney", "tiny-dungeon", "Tilemap", "tilemap_packed.png")
TOWN_SHEET = ("assets", "kenney", "tiny-town", "Tilemap", "tilemap_packed.png")

# Tiny Dungeon tile ids (row * 12 + col).
HERO = 88
KNIGHT = 96
GREEN_GHOST = 108
RED_SPIDER = 110
BAT = 120
GREY_GHOST = 121
CHEST = 89
POTION = 113
ALTAR = 32

_cache: dict[tuple[Path, int], pygame.Surface] = {}


def _placeholder(tile_id: int) -> pygame.Surface:
    surf = pygame.Surface((TILE, TILE), pygame.SRCALPHA)
    surf.fill((255, 0, 255, 255))
    pygame.draw.rect(surf, (0, 0, 0), surf.get_rect(), 1)
    return surf


def sheet_tile(tile_id: int, sheet: tuple[str, ...] = DUNGEON_SHEET) -> pygame.Surface:
    """Return tile ``tile_id`` from a Kenney packed sheet (magenta placeholder if missing)."""
    from coderogue.app import resource_path
    from coderogue.world.tilemap import load_image

    path = resource_path(*sheet)
    key = (path, tile_id)
    surf = _cache.get(key)
    if surf is None:
        if not path.exists():
            surf = _placeholder(tile_id)
        else:
            img = load_image(path)
            col, row = tile_id % SHEET_COLUMNS, tile_id // SHEET_COLUMNS
            surf = img.subsurface(pygame.Rect(col * TILE, row * TILE, TILE, TILE)).copy()
        _cache[key] = surf
    return surf


_sheet_cache: dict[tuple[Path, int], list[pygame.Surface]] = {}


def load_sheet(path: Path, frame_size: int = TILE) -> list[pygame.Surface]:
    """Split a horizontal strip of ``frame_size`` square frames (nearest-neighbour, no
    scaling) into surfaces. Cached; a missing file yields one magenta placeholder frame."""
    from coderogue.world.tilemap import load_image

    key = (Path(path), frame_size)
    frames = _sheet_cache.get(key)
    if frames is None:
        if not Path(path).exists():
            frames = [_placeholder(0)]
        else:
            img = load_image(Path(path))
            count = max(1, img.get_width() // frame_size)
            frames = [
                img.subsurface(pygame.Rect(i * frame_size, 0, frame_size, frame_size)).copy()
                for i in range(count)
            ]
        _sheet_cache[key] = frames
    return frames
