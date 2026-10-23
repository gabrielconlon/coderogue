"""Heads-up display drawn over the world: hearts, mode, XP/level, coins, ``u`` charges and
area name."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import pygame

from coderogue.progress import XP_PER_LEVEL
from coderogue.ui import theme
from coderogue.ui.panels import draw_panel
from coderogue.ui.text import draw_text, render_text

if TYPE_CHECKING:
    from coderogue.progress import Progress

HP_PER_HEART = 2
HEART_SIZE = 18
MODE_COLORS: dict[str, tuple[int, int, int]] = {
    "NORMAL": theme.ACCENT,
    "INSERT": theme.GOLD,
    "VISUAL": (150, 140, 240),
    "COMMAND": theme.WARN,
}


def heart_points(x: int, y: int, size: int) -> list[tuple[int, int]]:
    """A chunky pixel-art heart polygon with its top-left at (x, y)."""
    s = size / 8
    pts = [(1, 0), (3, 0), (4, 1), (5, 0), (7, 0), (8, 1), (8, 3), (4, 7), (0, 3), (0, 1)]
    return [(x + round(px * s), y + round(py * s)) for px, py in pts]


def draw_heart(surface: pygame.Surface, pos: tuple[int, int], fill: float, size: int) -> None:
    """Draw one heart; ``fill`` is 0 (empty), 0.5 (half) or 1 (full)."""
    x, y = pos
    pts = heart_points(x, y, size)
    pygame.draw.polygon(surface, theme.HEART_EMPTY, pts)
    if fill > 0:
        if fill >= 1:
            pygame.draw.polygon(surface, theme.HEART, pts)
        else:
            half = pygame.Surface((size + 1, size + 1), pygame.SRCALPHA)
            pygame.draw.polygon(half, theme.HEART, heart_points(0, 0, size))
            surface.blit(half, pos, pygame.Rect(0, 0, (size + 1) // 2, size + 1))
    pygame.draw.polygon(surface, (0, 0, 0), pts, 1)


def draw_hearts(surface: pygame.Surface, pos: tuple[int, int], hp: int, max_hp: int) -> int:
    """Draw ``max_hp / 2`` hearts filled to ``hp``; returns the x after the last heart."""
    x, y = pos
    hearts = max(1, (max_hp + HP_PER_HEART - 1) // HP_PER_HEART)
    for i in range(hearts):
        left = hp - i * HP_PER_HEART
        fill = 1.0 if left >= HP_PER_HEART else (0.5 if left > 0 else 0.0)
        draw_heart(surface, (x, y), fill, HEART_SIZE)
        x += HEART_SIZE + 4
    return x


def _mode_name(mode: Any) -> str:
    return str(getattr(mode, "value", mode) or "")


def draw_hud(
    surface: pygame.Surface,
    player: Any,
    progress: Progress | None,
    mode: Any,
    area_name: str = "",
) -> pygame.Rect:
    """Draw the HUD in the top-left corner and return its rect.

    ``player`` needs ``hp``/``max_hp``; optional ``coins`` and ``u_charges`` are shown when
    present. ``mode`` is a mode enum (``.value``) or a string.
    """
    hp = int(getattr(player, "hp", 0))
    max_hp = int(getattr(player, "max_hp", hp))
    name = _mode_name(mode)
    level = progress.level if progress is not None else 1
    xp = progress.xp_into_level if progress is not None else 0
    width = 340
    rect = pygame.Rect(6, 6, width, 52)
    draw_panel(surface, rect, (*theme.PANEL, 200), theme.BORDER)
    end = draw_hearts(surface, (rect.x + 8, rect.y + 7), hp, max_hp)
    label = render_text(f"-- {name} --", 14, MODE_COLORS.get(name, theme.TEXT), bold=True)
    surface.blit(label, (max(end + 8, rect.right - label.get_width() - 8), rect.y + 7))
    # XP bar and level.
    lv = f"Lv {level}"
    draw_text(surface, lv, (rect.x + 8, rect.y + 30), size=14, color=theme.GOLD)
    bar = pygame.Rect(rect.x + 60, rect.y + 35, 100, 8)
    surface.fill(theme.PANEL_ALT, bar)
    surface.fill(theme.GOLD, (bar.x, bar.y, bar.width * xp // XP_PER_LEVEL, bar.height))
    pygame.draw.rect(surface, theme.BORDER, bar, 1)
    x = bar.right + 10
    coins = getattr(player, "coins", None)
    if coins is not None:
        center = (x + 6, rect.y + 39)
        pygame.draw.circle(surface, theme.GOLD, center, 6)
        pygame.draw.circle(surface, (150, 110, 40), center, 6, 1)
        r = draw_text(surface, str(int(coins)), (x + 15, rect.y + 30), size=14, color=theme.GOLD)
        x = r.right + 10
    charges = getattr(player, "u_charges", None)
    if charges is not None:
        r = draw_text(surface, f"u:{int(charges)}", (x, rect.y + 30), size=14,
                      color=MODE_COLORS["VISUAL"])
        x = r.right + 10
    if area_name:
        name = area_name
        while name and x + render_text(name, 14).get_width() > rect.right - 6:
            name = name[:-2] + "…" if len(name) > 2 else ""
        draw_text(surface, name, (x, rect.y + 30), size=14, color=theme.MUTED)
    return rect
