"""Text rendering helpers using the bundled JetBrains Mono font."""

from __future__ import annotations

import pygame

FONT_REGULAR = ("assets", "fonts", "JetBrainsMono", "JetBrainsMono-Regular.ttf")
FONT_BOLD = ("assets", "fonts", "JetBrainsMono", "JetBrainsMono-Bold.ttf")

_fonts: dict[tuple[int, bool], pygame.font.Font] = {}


def get_font(size: int = 14, bold: bool = False) -> pygame.font.Font:
    """Return a cached JetBrains Mono font (falls back to pygame's default font)."""
    key = (size, bold)
    font = _fonts.get(key)
    if font is not None:
        try:
            font.get_height()
        except pygame.error:  # font died with pygame.quit(); rebuild it
            font = None
    if font is None:
        from coderogue.app import resource_path

        if not pygame.font.get_init():
            pygame.font.init()
        path = resource_path(*(FONT_BOLD if bold else FONT_REGULAR))
        font = pygame.font.Font(str(path) if path.exists() else None, size)
        _fonts[key] = font
    return font


def render_text(
    text: str, size: int = 14, color: tuple[int, int, int] = (230, 230, 230), bold: bool = False
) -> pygame.Surface:
    """Render a single line of text (antialiased: text is drawn at full res, not pixel art)."""
    try:
        return get_font(size, bold).render(text, True, color)
    except pygame.error:  # fonts die with pygame.quit(); rebuild after a re-init
        _fonts.clear()
        return get_font(size, bold).render(text, True, color)


def draw_text(
    surface: pygame.Surface,
    text: str,
    pos: tuple[int, int],
    size: int = 14,
    color: tuple[int, int, int] = (230, 230, 230),
    bold: bool = False,
    shadow: bool = True,
) -> pygame.Rect:
    """Draw ``text`` with its top-left at ``pos``; returns the drawn rect."""
    if shadow:
        surface.blit(render_text(text, size, (0, 0, 0), bold), (pos[0] + 1, pos[1] + 1))
    return surface.blit(render_text(text, size, color, bold), pos)
