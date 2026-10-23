"""One-line tutorial prompts, e.g. "Hold `h j k l` to walk", that fade once obeyed.

The world scene owns the hint: it calls ``update(dt)`` and ``draw(surface)`` each frame,
``dismiss()`` when the player does the thing (e.g. first movement), and drops the hint
when ``done`` is True. Text inside backticks is drawn in the accent colour as keys.
"""

from __future__ import annotations

import pygame

from coderogue.story.scene import ACCENT, PANEL_BG, TEXT
from coderogue.ui.text import render_text

FADE_IN = 0.4
FADE_OUT = 0.6
MIN_SHOW = 0.8  # a dismiss before this is honoured only after it has been readable


def split_keys(text: str) -> list[tuple[str, bool]]:
    """Split ``"Hold `h j k l` to walk"`` into ``[("Hold ", False), ("h j k l", True), ...]``."""
    parts = text.split("`")
    return [(p, i % 2 == 1) for i, p in enumerate(parts) if p]


class TutorialHint:
    """A centred pill near the bottom of the screen that fades in, waits, then fades out."""

    def __init__(
        self, text: str, size: int = 18, y_frac: float = 0.78, timeout: float | None = None
    ) -> None:
        self.text = text
        self.size = size
        self.y_frac = y_frac
        self.timeout = timeout
        self.age = 0.0
        self.dismissed_at: float | None = None
        self.done = False

    def dismiss(self) -> None:
        """Start fading out (the player did what the hint asked)."""
        if self.dismissed_at is None:
            self.dismissed_at = max(self.age, MIN_SHOW)

    @property
    def alpha(self) -> int:
        """Current opacity 0..255."""
        a = min(1.0, self.age / FADE_IN)
        if self.dismissed_at is not None and self.age > self.dismissed_at:
            a = min(a, max(0.0, 1.0 - (self.age - self.dismissed_at) / FADE_OUT))
        return int(255 * a)

    def update(self, dt: float) -> None:
        """Advance the fade."""
        self.age += dt
        if self.timeout is not None and self.age >= self.timeout:
            self.dismiss()
        if self.dismissed_at is not None and self.age >= self.dismissed_at + FADE_OUT:
            self.done = True

    def draw(self, surface: pygame.Surface) -> None:
        """Draw the hint (nothing once done)."""
        if self.done or self.alpha <= 0:
            return
        pieces = [
            render_text(seg, self.size, ACCENT if key else TEXT, bold=key)
            for seg, key in split_keys(self.text)
        ]
        w = sum(p.get_width() for p in pieces) + 32
        h = self.size + 18
        pill = pygame.Surface((w, h), pygame.SRCALPHA)
        pill.fill((*PANEL_BG, 220))
        x = 16
        for p in pieces:
            pill.blit(p, (x, (h - p.get_height()) // 2))
            x += p.get_width()
        pill.set_alpha(self.alpha)
        sw, sh = surface.get_size()
        surface.blit(pill, ((sw - w) // 2, int(sh * self.y_frac) - h // 2))
