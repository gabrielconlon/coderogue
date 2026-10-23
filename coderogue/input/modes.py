"""VIM-style mode machine shared by the world and the editor.

This module is deliberately dependency-free (no pygame) so the editor and tests can use it
without a display. It tracks the current :class:`Mode`, a numeric count prefix typed in
NORMAL mode (``3`` then ``j``), and the text typed on the ``:`` command line.
"""

from __future__ import annotations

from enum import Enum

MAX_COUNT = 999


class Mode(Enum):
    """The four stances of the Modal Order."""

    NORMAL = "NORMAL"
    INSERT = "INSERT"
    VISUAL = "VISUAL"
    COMMAND = "COMMAND"


class ModeMachine:
    """Current mode, pending count prefix and command-line buffer.

    Typical NORMAL-mode use::

        mm.feed_digit("3")       # True, consumed as a count
        mm.take_count()          # 3 (and the pending count is cleared)
        mm.take_count()          # 1 (default when nothing is pending)

    ``0`` only extends an existing count; on its own it is not a count (VIM treats a bare
    ``0`` as "start of line"), so ``feed_digit("0")`` returns False when nothing is pending.
    """

    def __init__(self, mode: Mode = Mode.NORMAL) -> None:
        self.mode: Mode = mode
        self._count: str = ""
        self.command_buffer: str = ""

    # ---- mode -------------------------------------------------------------------------
    def set_mode(self, mode: Mode) -> None:
        """Switch mode. Entering COMMAND clears the command buffer; any switch drops the count."""
        if mode is Mode.COMMAND:
            self.command_buffer = ""
        self.mode = mode
        self._count = ""

    def escape(self) -> None:
        """``Esc``: back to NORMAL, dropping any pending count and command text."""
        self.mode = Mode.NORMAL
        self._count = ""
        self.command_buffer = ""

    # ---- count prefix ----------------------------------------------------------------
    @property
    def pending_count(self) -> int | None:
        """The count typed so far, or None if no digits are pending."""
        return int(self._count) if self._count else None

    @property
    def count_text(self) -> str:
        """Raw digits typed so far (for display)."""
        return self._count

    def feed_digit(self, ch: str) -> bool:
        """Offer a character as part of a count. Returns True if it was consumed."""
        if self.mode is not Mode.NORMAL and self.mode is not Mode.VISUAL:
            return False
        if len(ch) != 1 or not ch.isdigit():
            return False
        if ch == "0" and not self._count:
            return False
        candidate = self._count + ch
        self._count = str(min(int(candidate), MAX_COUNT))
        return True

    def take_count(self, default: int = 1) -> int:
        """Return the pending count (or ``default``) and clear it."""
        value = int(self._count) if self._count else default
        self._count = ""
        return value

    def clear_count(self) -> None:
        """Drop any pending count."""
        self._count = ""

    # ---- command line ----------------------------------------------------------------
    def command_type(self, text: str) -> None:
        """Append text to the command line (only in COMMAND mode)."""
        if self.mode is Mode.COMMAND:
            self.command_buffer += text

    def command_backspace(self) -> None:
        """Delete one char; backspacing an empty command line returns to NORMAL like VIM."""
        if self.mode is not Mode.COMMAND:
            return
        if self.command_buffer:
            self.command_buffer = self.command_buffer[:-1]
        else:
            self.escape()

    def command_submit(self) -> str:
        """Return the command text (without ``:``), clear it and go back to NORMAL."""
        text = self.command_buffer.strip()
        self.escape()
        return text
