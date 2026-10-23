"""Panel drawing and word wrapping helpers."""

from __future__ import annotations

import pygame

from coderogue.ui import text as _text
from coderogue.ui import theme
from coderogue.ui.text import get_font


def live_font(size: int = 14, bold: bool = False) -> pygame.font.Font:
    """Like :func:`~coderogue.ui.text.get_font`, but rebuilds the cache if the cached font
    died with an earlier ``pygame.quit()`` (``get_font`` alone would hand back a dead font)."""
    font = get_font(size, bold)
    try:
        font.size("M")
    except pygame.error:
        _text._fonts.clear()
        font = get_font(size, bold)
    return font


def draw_panel(
    surface: pygame.Surface,
    rect: pygame.Rect | tuple[int, int, int, int],
    fill: tuple[int, ...] = theme.PANEL,
    border: tuple[int, int, int] | None = theme.BORDER,
    width: int = 1,
) -> pygame.Rect:
    """Fill ``rect`` and draw a ``width`` px border. A 4-tuple ``fill`` is drawn with alpha."""
    rect = pygame.Rect(rect)
    if len(fill) == 4 and fill[3] < 255:
        layer = pygame.Surface(rect.size, pygame.SRCALPHA)
        layer.fill(fill)
        surface.blit(layer, rect.topleft)
    else:
        surface.fill(fill[:3], rect)
    if border is not None and width > 0:
        pygame.draw.rect(surface, border, rect, width)
    return rect


def _split_long(font: pygame.font.Font, word: str, width: int) -> list[str]:
    """Hard-break a single word that is wider than ``width``."""
    parts: list[str] = []
    cur = ""
    for ch in word:
        if cur and font.size(cur + ch)[0] > width:
            parts.append(cur)
            cur = ch
        else:
            cur += ch
    if cur:
        parts.append(cur)
    return parts


def wrap_text(font: pygame.font.Font, text: str, width: int) -> list[str]:
    """Word-wrap ``text`` to lines no wider than ``width`` px. Newlines start new lines.

    Leading indentation of each source line is kept; over-long words are broken.
    """
    out: list[str] = []
    for para in text.replace("\r\n", "\n").split("\n"):
        if not para.strip():
            out.append("")
            continue
        indent = para[: len(para) - len(para.lstrip(" "))]
        line = ""
        for word in para.split():
            candidate = f"{line} {word}" if line else indent + word
            if font.size(candidate)[0] <= width:
                line = candidate
                continue
            if line:
                out.append(line)
            if font.size(indent + word)[0] <= width:
                line = indent + word
            else:
                pieces = _split_long(font, word, max(1, width))
                out.extend(pieces[:-1])
                line = pieces[-1]
        out.append(line)
    return out
