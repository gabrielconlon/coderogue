"""Axis-aligned box vs tile-grid collision. Pure Python: no pygame import.

Movement is resolved one axis at a time (X then Y), which is what makes sliding along a
wall work: a diagonal push into a wall keeps the parallel component.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass


class CollisionGrid:
    """A grid of solid/non-solid tiles. Out-of-bounds counts as solid."""

    def __init__(self, width: int, height: int, tile_size: int, solid: Sequence[bool]) -> None:
        if len(solid) != width * height:
            raise ValueError("solid must have width*height entries")
        self.width = width
        self.height = height
        self.tile_size = tile_size
        self.solid: list[bool] = list(solid)

    @classmethod
    def from_rows(cls, rows: Sequence[str], tile_size: int = 16) -> CollisionGrid:
        """Build from ASCII rows where ``#`` is solid (handy in tests)."""
        height = len(rows)
        width = len(rows[0]) if rows else 0
        return cls(width, height, tile_size, [ch == "#" for row in rows for ch in row])

    def is_solid(self, tx: int, ty: int) -> bool:
        """True if tile (tx, ty) blocks movement."""
        if 0 <= tx < self.width and 0 <= ty < self.height:
            return self.solid[ty * self.width + tx]
        return True

    def set_solid(self, tx: int, ty: int, value: bool) -> None:
        """Mark a tile solid or open (doors, destructible walls)."""
        if 0 <= tx < self.width and 0 <= ty < self.height:
            self.solid[ty * self.width + tx] = value

    def box_hits(self, x: float, y: float, w: float, h: float) -> bool:
        """True if the box overlaps any solid tile."""
        ts = self.tile_size
        x0 = math.floor(x / ts)
        y0 = math.floor(y / ts)
        x1 = math.ceil((x + w) / ts) - 1
        y1 = math.ceil((y + h) / ts) - 1
        for ty in range(y0, y1 + 1):
            for tx in range(x0, x1 + 1):
                if self.is_solid(tx, ty):
                    return True
        return False


@dataclass
class MoveResult:
    """Outcome of :func:`move_box`."""

    x: float
    y: float
    hit_x: bool
    hit_y: bool


def _sweep_axis(
    grid: CollisionGrid, x: float, y: float, w: float, h: float, delta: float, axis: int
) -> tuple[float, bool]:
    """Move along one axis, stopping flush against the first solid tile."""
    pos = x if axis == 0 else y
    if delta == 0:
        return pos, False
    ts = grid.tile_size
    step_max = ts / 2
    steps = max(1, math.ceil(abs(delta) / step_max))
    step = delta / steps
    for _ in range(steps):
        new = pos + step
        bx, by = (new, y) if axis == 0 else (x, new)
        if not grid.box_hits(bx, by, w, h):
            pos = new
            continue
        size = w if axis == 0 else h
        if step > 0:
            # leading edge entered tile index floor((new+size)/ts); stand flush to its left/top
            tile = math.floor((new + size) / ts - 1e-9)
            pos = max(pos, tile * ts - size)
        else:
            tile = math.floor(new / ts)
            pos = min(pos, (tile + 1) * ts)
        return pos, True
    return pos, False


def move_box(
    grid: CollisionGrid, x: float, y: float, w: float, h: float, dx: float, dy: float
) -> MoveResult:
    """Move box (x, y, w, h) by (dx, dy) against ``grid`` with axis-separated resolution."""
    nx, hit_x = _sweep_axis(grid, x, y, w, h, dx, 0)
    ny, hit_y = _sweep_axis(grid, nx, y, w, h, dy, 1)
    return MoveResult(nx, ny, hit_x, hit_y)


def boxes_overlap(
    a: tuple[float, float, float, float], b: tuple[float, float, float, float]
) -> bool:
    """Strict AABB overlap of two (x, y, w, h) boxes."""
    ax, ay, aw, ah = a
    bx, by, bw, bh = b
    return ax < bx + bw and bx < ax + aw and ay < by + bh and by < ay + ah
