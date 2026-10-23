"""Pure-Python text buffer for the altar editor (no pygame).

Positions are ``(row, col)`` tuples, zero based. A charwise range ``(start, end)`` is half-open:
``end`` is exclusive and may be ``(row, len(line))`` to reach the end of a line. The text of the
buffer is always ``"\\n".join(lines)``; a buffer is never empty (it holds at least ``[""]``).
"""

from __future__ import annotations

from dataclasses import dataclass

Pos = tuple[int, int]

UNDO_LIMIT = 200


@dataclass(frozen=True)
class Snapshot:
    """An immutable copy of buffer state used by the undo and redo stacks."""

    lines: tuple[str, ...]
    cursor: Pos


class Buffer:
    """Lines of text plus a cursor, primitive edit operations, and snapshot undo/redo.

    Undo model: callers bracket a logical change with :meth:`begin_change` and
    :meth:`end_change`. ``begin_change`` records the state before the change; ``end_change``
    drops that record again if the text did not actually change. The Vim layer opens a change
    for each NORMAL-mode operator and for each INSERT session (closed on ``<Esc>``).
    """

    def __init__(self, text: str = "") -> None:
        self.lines: list[str] = text.split("\n") if text else [""]
        self.row = 0
        self.col = 0
        self._undo: list[Snapshot] = []
        self._redo: list[Snapshot] = []
        self._open: Snapshot | None = None

    # ----------------------------------------------------------------- text access
    @property
    def text(self) -> str:
        """The whole buffer as one string, lines joined with ``\\n``."""
        return "\n".join(self.lines)

    @text.setter
    def text(self, value: str) -> None:
        self.set_text(value)

    def get_text(self) -> str:
        """Return the buffer text (same as :attr:`text`)."""
        return self.text

    def set_text(self, text: str, reset_history: bool = True) -> None:
        """Replace all text, put the cursor at (0, 0) and (by default) clear undo history."""
        self.lines = text.split("\n") if text else [""]
        self.row = 0
        self.col = 0
        if reset_history:
            self._undo.clear()
            self._redo.clear()
            self._open = None

    @property
    def cursor(self) -> Pos:
        """The cursor as ``(row, col)``."""
        return (self.row, self.col)

    @cursor.setter
    def cursor(self, pos: Pos) -> None:
        self.row, self.col = pos

    def line(self, row: int | None = None) -> str:
        """Return line ``row`` (default: the cursor row)."""
        return self.lines[self.row if row is None else row]

    def line_count(self) -> int:
        """Number of lines (always at least 1)."""
        return len(self.lines)

    def clamp(self, insert: bool = False) -> None:
        """Clamp the cursor like Vim.

        In NORMAL mode (``insert=False``) the cursor may not sit past the last character; in
        INSERT mode it may sit at ``len(line)``.
        """
        self.row = max(0, min(self.row, len(self.lines) - 1))
        n = len(self.lines[self.row])
        limit = n if insert else max(0, n - 1)
        self.col = max(0, min(self.col, limit))

    # ----------------------------------------------------------------- offsets
    def offset(self, pos: Pos) -> int:
        """Convert ``(row, col)`` to an offset into :attr:`text`."""
        row, col = pos
        return sum(len(line) + 1 for line in self.lines[:row]) + col

    def pos_from_offset(self, offset: int) -> Pos:
        """Convert an offset into :attr:`text` back to ``(row, col)``."""
        for row, line in enumerate(self.lines):
            if offset <= len(line):
                return (row, max(0, offset))
            offset -= len(line) + 1
        last = len(self.lines) - 1
        return (last, len(self.lines[last]))

    # ----------------------------------------------------------------- primitives
    def insert_text(self, pos: Pos, text: str) -> Pos:
        """Insert ``text`` (may contain newlines) at ``pos``; return the position after it."""
        row, col = pos
        line = self.lines[row]
        head, tail = line[:col], line[col:]
        parts = text.split("\n")
        if len(parts) == 1:
            self.lines[row] = head + text + tail
            return (row, col + len(text))
        new = [head + parts[0], *parts[1:-1], parts[-1] + tail]
        self.lines[row : row + 1] = new
        return (row + len(parts) - 1, len(parts[-1]))

    def delete_range(self, start: Pos, end: Pos) -> str:
        """Delete the half-open charwise range ``[start, end)`` and return the removed text."""
        if end < start:
            start, end = end, start
        (r1, c1), (r2, c2) = start, end
        if r1 == r2:
            line = self.lines[r1]
            removed = line[c1:c2]
            self.lines[r1] = line[:c1] + line[c2:]
            return removed
        removed = "\n".join([self.lines[r1][c1:], *self.lines[r1 + 1 : r2], self.lines[r2][:c2]])
        self.lines[r1 : r2 + 1] = [self.lines[r1][:c1] + self.lines[r2][c2:]]
        return removed

    def get_range(self, start: Pos, end: Pos) -> str:
        """Return the text in the half-open charwise range ``[start, end)``."""
        if end < start:
            start, end = end, start
        (r1, c1), (r2, c2) = start, end
        if r1 == r2:
            return self.lines[r1][c1:c2]
        return "\n".join([self.lines[r1][c1:], *self.lines[r1 + 1 : r2], self.lines[r2][:c2]])

    def split_line(self, pos: Pos, indent: str = "") -> Pos:
        """Split the line at ``pos``; the new line starts with ``indent``. Returns its start."""
        row, col = pos
        line = self.lines[row]
        self.lines[row : row + 1] = [line[:col], indent + line[col:]]
        return (row + 1, len(indent))

    def join_lines(self, row: int, sep: str = "") -> Pos:
        """Join line ``row + 1`` onto line ``row`` with ``sep``; return the join point."""
        if row + 1 >= len(self.lines):
            return (row, len(self.lines[row]))
        col = len(self.lines[row])
        self.lines[row : row + 2] = [self.lines[row] + sep + self.lines[row + 1]]
        return (row, col)

    def insert_lines(self, row: int, lines: list[str]) -> None:
        """Insert whole lines so that the first one becomes line ``row``."""
        self.lines[row:row] = list(lines)

    def delete_lines(self, r1: int, r2: int) -> list[str]:
        """Delete lines ``r1..r2`` inclusive and return them. Keeps at least one empty line."""
        if r2 < r1:
            r1, r2 = r2, r1
        removed = self.lines[r1 : r2 + 1]
        del self.lines[r1 : r2 + 1]
        if not self.lines:
            self.lines = [""]
        return removed

    # ----------------------------------------------------------------- undo / redo
    def snapshot(self) -> Snapshot:
        """Capture the current lines and cursor."""
        return Snapshot(tuple(self.lines), (self.row, self.col))

    def restore(self, snap: Snapshot) -> None:
        """Restore lines and cursor from a snapshot."""
        self.lines = list(snap.lines)
        self.row, self.col = snap.cursor

    def begin_change(self) -> None:
        """Record the pre-change state. Nested calls are ignored until :meth:`end_change`."""
        if self._open is None:
            self._open = self.snapshot()

    def end_change(self) -> bool:
        """Close the open change; push it on the undo stack if the text changed.

        Returns True when an undo step was recorded.
        """
        snap, self._open = self._open, None
        if snap is None or snap.lines == tuple(self.lines):
            return False
        self._undo.append(snap)
        del self._undo[:-UNDO_LIMIT]
        self._redo.clear()
        return True

    def push_undo(self) -> None:
        """Unconditionally push the current state on the undo stack (clears redo)."""
        self._undo.append(self.snapshot())
        del self._undo[:-UNDO_LIMIT]
        self._redo.clear()

    @property
    def can_undo(self) -> bool:
        """True when there is something to undo."""
        return bool(self._undo)

    @property
    def can_redo(self) -> bool:
        """True when there is something to redo."""
        return bool(self._redo)

    def undo(self) -> bool:
        """Revert the last recorded change. Returns False when there is nothing to undo."""
        if not self._undo:
            return False
        self._redo.append(self.snapshot())
        self.restore(self._undo.pop())
        return True

    def redo(self) -> bool:
        """Re-apply the last undone change. Returns False when there is nothing to redo."""
        if not self._redo:
            return False
        self._undo.append(self.snapshot())
        snap = self._redo.pop()
        self.restore(snap)
        return True
