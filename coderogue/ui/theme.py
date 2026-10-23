"""Shared UI palette for the HUD, panels and the altar scene."""

from __future__ import annotations

Color = tuple[int, int, int]

PANEL: Color = (14, 13, 18)  # #0e0d12, dark panel fill
PANEL_ALT: Color = (24, 22, 32)  # slightly lighter panel (tabs, diff header)
BORDER: Color = (58, 54, 74)
ACCENT: Color = (80, 200, 160)  # #50c8a0, editor accent green (NORMAL, success)
WARN: Color = (232, 150, 90)  # failures, diff highlight text
ERROR: Color = (226, 96, 104)
TEXT: Color = (228, 226, 236)
MUTED: Color = (140, 136, 160)
DIM: Color = (88, 84, 104)  # greyed-out (unavailable language tab)
HEART: Color = (220, 64, 84)
HEART_EMPTY: Color = (60, 40, 52)
GOLD: Color = (240, 200, 110)
DIFF_HIGHLIGHT: Color = (70, 38, 34)  # background of the first differing diff row
SCRIM_ALPHA = 150  # how strongly a modal darkens the frozen world behind it
