"""pygame view for :class:`~coderogue.editor.vim.VimEditor`.

Everything is drawn on a monospace character grid at integer pixel positions (no smoothscale),
so the editor stays crisp when the game scales its frame up with nearest-neighbour.
"""

from __future__ import annotations

from dataclasses import dataclass

import pygame

from coderogue.editor.highlight import tokenize_line
from coderogue.editor.vim import Mode, VimEditor

Color = tuple[int, int, int]


@dataclass
class EditorTheme:
    """Colours used by :class:`EditorView`. Token colours are keyed by highlighter kind."""

    background: Color = (20, 22, 30)
    text: Color = (214, 218, 228)
    gutter_bg: Color = (28, 31, 42)
    gutter_fg: Color = (98, 104, 128)
    gutter_current: Color = (230, 200, 110)
    gutter_error_bg: Color = (120, 36, 44)
    cursor: Color = (240, 210, 120)
    cursor_text: Color = (20, 22, 30)
    selection: Color = (60, 74, 120)
    status_bg: Color = (36, 40, 56)
    status_fg: Color = (230, 230, 240)
    message_fg: Color = (240, 150, 130)
    keyword: Color = (198, 120, 221)
    builtin: Color = (97, 175, 239)
    string: Color = (152, 195, 121)
    comment: Color = (110, 118, 140)
    number: Color = (209, 154, 102)
    variable: Color = (224, 108, 117)

    def token_color(self, kind: str) -> Color:
        """Colour for a highlighter token kind (falls back to :attr:`text`)."""
        value = getattr(self, kind, None) if kind != "text" else None
        return value if isinstance(value, tuple) else self.text


DEFAULT_THEME = EditorTheme()

_STATUS_LABELS = {
    Mode.INSERT: "-- INSERT --",
    Mode.VISUAL: "-- VISUAL --",
    Mode.VISUAL_LINE: "-- VISUAL LINE --",
}


class EditorView:
    """Draws a :class:`VimEditor`: gutter, highlighted text, selection, cursor, status line.

    ``language`` selects the highlighter (``"python"``, ``"bash"``, ``"powershell"`` or None).
    ``error_lines`` holds zero-based rows whose gutter number should glow (failed casts).
    ``line_font`` (optional) is used for the status line; defaults to ``font``.
    """

    def __init__(
        self,
        editor: VimEditor,
        font: pygame.font.Font,
        line_font: pygame.font.Font | None = None,
        language: str | None = None,
        antialias: bool = True,
    ) -> None:
        self.editor = editor
        self.font = font
        self.line_font = line_font or font
        self.language = language
        self.antialias = antialias
        self.error_lines: set[int] = set()
        self.scroll_row = 0
        self.scroll_col = 0
        self.char_w = max(1, font.size("M")[0])
        self.line_h = max(1, font.get_linesize())
        self._cache: dict[tuple[str, Color, Color | None], pygame.Surface] = {}

    # ----------------------------------------------------------------- helpers
    def _glyphs(self, text: str, color: Color, bg: Color | None = None) -> pygame.Surface:
        key = (text, color, bg)
        surf = self._cache.get(key)
        if surf is None:
            if len(self._cache) > 4000:
                self._cache.clear()
            surf = self.font.render(text.replace("\t", " "), self.antialias, color, bg)
            self._cache[key] = surf
        return surf

    def visible_rows(self, rect: pygame.Rect) -> int:
        """How many text rows fit in ``rect`` (one row is reserved for the status line)."""
        return max(1, rect.height // self.line_h - 1)

    def _scroll_to_cursor(self, rows: int, cols: int) -> None:
        row, col = self.editor.cursor
        if row < self.scroll_row:
            self.scroll_row = row
        elif row >= self.scroll_row + rows:
            self.scroll_row = row - rows + 1
        self.scroll_row = max(0, min(self.scroll_row, max(0, len(self.editor.lines) - 1)))
        if col < self.scroll_col:
            self.scroll_col = col
        elif col >= self.scroll_col + cols:
            self.scroll_col = col - cols + 1

    def _selection_span(self, row: int) -> tuple[int, int] | None:
        """Selected columns ``[c1, c2)`` on ``row`` (in buffer columns), or None."""
        rng = self.editor.visual_range()
        if rng is None:
            return None
        (r1, c1), (r2, c2), linewise = rng
        if not r1 <= row <= r2:
            return None
        length = len(self.editor.lines[row])
        if linewise:
            return (0, length + 1)
        start = c1 if row == r1 else 0
        end = c2 + 1 if row == r2 else length + 1
        return (start, end)

    # ----------------------------------------------------------------- draw
    def draw(
        self, surface: pygame.Surface, rect: pygame.Rect, theme: EditorTheme | None = None
    ) -> None:
        """Draw the editor into ``rect`` on ``surface``."""
        theme = theme or DEFAULT_THEME
        rect = pygame.Rect(rect)
        cw, lh = self.char_w, self.line_h
        lines = self.editor.lines
        digits = max(2, len(str(len(lines))))
        gutter_w = (digits + 2) * cw
        text_x = rect.x + gutter_w
        rows = self.visible_rows(rect)
        cols = max(1, (rect.width - gutter_w) // cw - 1)
        self._scroll_to_cursor(rows, cols)

        old_clip = surface.get_clip()
        surface.set_clip(rect)
        surface.fill(theme.background, rect)
        surface.fill(theme.gutter_bg, pygame.Rect(rect.x, rect.y, gutter_w, rows * lh))

        cur_row, cur_col = self.editor.cursor
        text_clip = pygame.Rect(text_x, rect.y, rect.right - text_x, rows * lh).clip(rect)
        for screen_row in range(rows):
            row = self.scroll_row + screen_row
            if row >= len(lines):
                break
            y = rect.y + screen_row * lh
            # Gutter.
            if row in self.error_lines:
                surface.fill(theme.gutter_error_bg, pygame.Rect(rect.x, y, gutter_w, lh))
            num_color = theme.gutter_current if row == cur_row else theme.gutter_fg
            num = self._glyphs(str(row + 1).rjust(digits), num_color)
            surface.blit(num, (rect.x + cw // 2, y))
            # Selection.
            surface.set_clip(text_clip)
            span = self._selection_span(row)
            if span is not None:
                c1 = max(span[0] - self.scroll_col, 0)
                c2 = span[1] - self.scroll_col
                if c2 > c1:
                    sel = pygame.Rect(text_x + c1 * cw, y, (c2 - c1) * cw, lh)
                    surface.fill(theme.selection, sel)
            # Text.
            x = text_x - self.scroll_col * cw
            for text, kind in tokenize_line(lines[row], self.language):
                width = len(text) * cw
                if x + width > text_x and x < rect.right:
                    surface.blit(self._glyphs(text, theme.token_color(kind)), (x, y))
                x += width
            surface.set_clip(rect)

        self._draw_cursor(surface, rect, theme, text_x, rows, text_clip)
        self._draw_status(surface, rect, theme, rows)
        surface.set_clip(old_clip)

    def _draw_cursor(
        self,
        surface: pygame.Surface,
        rect: pygame.Rect,
        theme: EditorTheme,
        text_x: int,
        rows: int,
        text_clip: pygame.Rect,
    ) -> None:
        mode = self.editor.mode
        if mode in (Mode.COMMAND, Mode.SEARCH):
            return
        cw, lh = self.char_w, self.line_h
        row, col = self.editor.cursor
        screen_row = row - self.scroll_row
        if not 0 <= screen_row < rows:
            return
        x = text_x + (col - self.scroll_col) * cw
        y = rect.y + screen_row * lh
        surface.set_clip(text_clip)
        if mode is Mode.INSERT:
            surface.fill(theme.cursor, pygame.Rect(x, y, max(2, cw // 6), lh))
        else:
            surface.fill(theme.cursor, pygame.Rect(x, y, cw, lh))
            line = self.editor.lines[row]
            if col < len(line) and not line[col].isspace():
                surface.blit(self._glyphs(line[col], theme.cursor_text), (x, y))
        surface.set_clip(rect)

    def _draw_status(
        self, surface: pygame.Surface, rect: pygame.Rect, theme: EditorTheme, rows: int
    ) -> None:
        ed = self.editor
        y = rect.y + rows * self.line_h
        bar = pygame.Rect(rect.x, y, rect.width, rect.bottom - y)
        surface.fill(theme.status_bg, bar)
        font = self.line_font
        pad = self.char_w // 2
        if ed.mode is Mode.COMMAND:
            left = ":" + ed.cmdline
        elif ed.mode is Mode.SEARCH:
            left = "/" + ed.cmdline
        else:
            left = _STATUS_LABELS.get(ed.mode, "")
        x = rect.x + pad
        if left:
            surf = font.render(left, self.antialias, theme.status_fg)
            surface.blit(surf, (x, y))
            x += surf.get_width() + self.char_w
            if ed.mode in (Mode.COMMAND, Mode.SEARCH):
                cursor = pygame.Rect(x - self.char_w, y, max(2, self.char_w // 6), self.line_h)
                surface.fill(theme.cursor, cursor)
        if ed.last_message and ed.mode not in (Mode.COMMAND, Mode.SEARCH):
            surface.blit(font.render(ed.last_message, self.antialias, theme.message_fg), (x, y))
        row, col = ed.cursor
        right = f"{ed.pending}   {row + 1},{col + 1}"
        surf = font.render(right, self.antialias, theme.status_fg)
        surface.blit(surf, (rect.right - surf.get_width() - pad, y))
