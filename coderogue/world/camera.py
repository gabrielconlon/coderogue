"""Camera that follows a point and clamps to the map. Pure Python: no pygame import."""

from __future__ import annotations


class Camera:
    """Top-left offset of the view into the world, in world pixels.

    If the map is smaller than the view on an axis, the map is centred on that axis.
    """

    def __init__(self, view_w: int, view_h: int, world_w: int, world_h: int) -> None:
        self.view_w = view_w
        self.view_h = view_h
        self.world_w = world_w
        self.world_h = world_h
        self.x: float = 0.0
        self.y: float = 0.0

    @staticmethod
    def _clamp_axis(center: float, view: int, world: int) -> float:
        if world <= view:
            return -(view - world) / 2
        return min(max(center - view / 2, 0.0), float(world - view))

    def follow(self, cx: float, cy: float) -> None:
        """Centre on (cx, cy), clamped so the view never leaves the map."""
        self.x = self._clamp_axis(cx, self.view_w, self.world_w)
        self.y = self._clamp_axis(cy, self.view_h, self.world_h)

    @property
    def offset(self) -> tuple[int, int]:
        """Integer offset (round once so all sprites move in lockstep, no shimmer)."""
        return (round(self.x), round(self.y))

    def to_screen(self, x: float, y: float) -> tuple[int, int]:
        """World pixel -> view pixel."""
        ox, oy = self.offset
        return (round(x) - ox, round(y) - oy)
