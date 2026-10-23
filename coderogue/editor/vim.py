"""Modal VIM-like editing state machine (pure Python, no pygame).

Drive it with :meth:`VimEditor.feed_key`. Keys are strings: a single printable character
(``"h"``, ``"$"``, ``"A"``) or a bracketed special key: ``"<Esc>"``, ``"<CR>"``, ``"<BS>"``,
``"<Tab>"``, ``"<C-r>"``, ``"<Left>"``, ``"<Right>"``, ``"<Up>"``, ``"<Down>"``, ``"<Del>"``.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum

from coderogue.editor.buffer import Buffer, Pos

TAB_SPACES = "    "

ARROWS = {"<Left>": "h", "<Right>": "l", "<Up>": "k", "<Down>": "j"}

# Motions understood after a count and/or operator. Values are the motion kind:
# "excl" (charwise exclusive), "incl" (charwise inclusive) or "line" (linewise).
MOTIONS: dict[str, str] = {
    "h": "excl",
    "l": "excl",
    "j": "line",
    "k": "line",
    "w": "excl",
    "b": "excl",
    "e": "incl",
    "0": "excl",
    "^": "excl",
    "$": "incl",
    "gg": "line",
    "G": "line",
}


class Mode(StrEnum):
    """Editor modes (the Four Stances, plus the two line-input sub-modes)."""

    NORMAL = "NORMAL"
    INSERT = "INSERT"
    VISUAL = "VISUAL"
    VISUAL_LINE = "VISUAL LINE"
    COMMAND = "COMMAND"
    SEARCH = "SEARCH"


@dataclass
class Register:
    """The unnamed register: yanked or deleted text and whether it is linewise."""

    text: str = ""
    linewise: bool = False


def char_class(ch: str) -> int:
    """Vim word class: 0 whitespace (incl. newline), 1 keyword chars, 2 punctuation."""
    if ch in " \t\n":
        return 0
    if ch.isalnum() or ch == "_":
        return 1
    return 2


def _is_empty_line_at(s: str, i: int) -> bool:
    """True when offset ``i`` in flat text ``s`` is the start of an empty line."""
    n = len(s)
    if i == n:
        return n == 0 or s[n - 1] == "\n"
    return s[i] == "\n" and (i == 0 or s[i - 1] == "\n")


def word_forward(s: str, i: int) -> int:
    """Offset of the next word start after ``i`` (Vim ``w``). May return ``len(s)``."""
    n = len(s)
    if i >= n:
        return n
    cls = char_class(s[i])
    if cls:
        while i < n and char_class(s[i]) == cls:
            i += 1
    while i < n and char_class(s[i]) == 0:
        if s[i] == "\n":
            i += 1
            if _is_empty_line_at(s, i):
                return i
            continue
        i += 1
    return i


def word_end(s: str, i: int) -> int:
    """Offset of the next word end after ``i`` (Vim ``e``)."""
    n = len(s)
    if n == 0:
        return 0
    i += 1
    while i < n and char_class(s[i]) == 0:
        i += 1
    if i >= n:
        return n - 1
    cls = char_class(s[i])
    while i + 1 < n and char_class(s[i + 1]) == cls:
        i += 1
    return i


def word_backward(s: str, i: int) -> int:
    """Offset of the previous word start before ``i`` (Vim ``b``)."""
    if i <= 0:
        return 0
    i -= 1
    while i > 0 and char_class(s[i]) == 0 and not _is_empty_line_at(s, i):
        i -= 1
    if char_class(s[i]) == 0:
        return i
    cls = char_class(s[i])
    while i > 0 and char_class(s[i - 1]) == cls:
        i -= 1
    return i


def first_nonblank(line: str) -> int:
    """Column of the first non-blank character (Vim ``^``); 0 for blank lines."""
    stripped = len(line) - len(line.lstrip(" \t"))
    return min(stripped, max(0, len(line) - 1))


class VimEditor:
    """A modal editor over a :class:`Buffer`, fed one key string at a time.

    ``on_command`` receives the text of an ex command line (without the leading ``:``) when
    the player presses ``<CR>`` in COMMAND mode. The editor itself only swallows ``:set``.
    """

    def __init__(
        self,
        buffer: Buffer | None = None,
        on_command: Callable[[str], None] | None = None,
    ) -> None:
        self.buffer = buffer if buffer is not None else Buffer()
        self.on_command = on_command
        self.mode = Mode.NORMAL
        self.register = Register()
        self.cmdline = ""
        self.last_message = ""
        self.last_search: str | None = None
        self._count = ""
        self._op = ""
        self._op_count = ""
        self._g = False
        self._want_col: int | None = None
        self._anchor: Pos = (0, 0)
        self.buffer.clamp()

    # ----------------------------------------------------------------- public state
    @property
    def cursor(self) -> Pos:
        """The cursor as ``(row, col)``."""
        return self.buffer.cursor

    @cursor.setter
    def cursor(self, pos: Pos) -> None:
        self.buffer.cursor = pos
        self.buffer.clamp(insert=self.mode is Mode.INSERT)
        self._want_col = None

    @property
    def text(self) -> str:
        """The buffer text."""
        return self.buffer.text

    @text.setter
    def text(self, value: str) -> None:
        self.set_text(value)

    def set_text(self, text: str) -> None:
        """Load new text (e.g. puzzle starter code): resets cursor, mode, undo history."""
        self.buffer.set_text(text)
        self.mode = Mode.NORMAL
        self.cmdline = ""
        self.last_message = ""
        self._reset_pending()

    @property
    def pending(self) -> str:
        """The partially typed NORMAL command, e.g. ``"3"``, ``"d"``, ``"2d3"``, ``"g"``."""
        return self._count + self._op + self._op_count + ("g" if self._g else "")

    @property
    def lines(self) -> list[str]:
        """The buffer lines (live list; do not mutate)."""
        return self.buffer.lines

    def visual_range(self) -> tuple[Pos, Pos, bool] | None:
        """Return ``(start, end, linewise)`` of the VISUAL selection, or None.

        ``start <= end``; both ends are inclusive. For linewise selections the columns span the
        full lines (``end`` col is ``len(line)``).
        """
        if self.mode not in (Mode.VISUAL, Mode.VISUAL_LINE):
            return None
        a, b = sorted((self._anchor, self.cursor))
        if self.mode is Mode.VISUAL_LINE:
            return ((a[0], 0), (b[0], len(self.lines[b[0]])), True)
        return (a, b, False)

    # ----------------------------------------------------------------- dispatch
    def feed_key(self, key: str) -> None:
        """Process one key in the current mode."""
        handler = {
            Mode.NORMAL: self._normal_key,
            Mode.INSERT: self._insert_key,
            Mode.VISUAL: self._visual_key,
            Mode.VISUAL_LINE: self._visual_key,
            Mode.COMMAND: self._line_key,
            Mode.SEARCH: self._line_key,
        }[self.mode]
        handler(key)

    def feed_keys(self, keys: str | list[str]) -> None:
        """Feed several keys. A string is split into keys, honouring ``<...>`` names."""
        for key in split_keys(keys) if isinstance(keys, str) else keys:
            self.feed_key(key)

    # ----------------------------------------------------------------- helpers
    def _reset_pending(self) -> None:
        self._count = ""
        self._op = ""
        self._op_count = ""
        self._g = False

    def _take_count(self) -> tuple[int, bool]:
        """Combined count of ``[count]op[count]`` and whether any count was typed."""
        typed = bool(self._count or self._op_count)
        n = int(self._count or 1) * int(self._op_count or 1)
        return n, typed

    def _flat(self) -> str:
        return self.buffer.text

    def _set_cursor(self, pos: Pos, keep_want: bool = False) -> None:
        self.buffer.cursor = pos
        self.buffer.clamp(insert=self.mode is Mode.INSERT)
        if not keep_want:
            self._want_col = None

    # ----------------------------------------------------------------- motions
    def _motion(self, key: str, count: int, typed: bool, for_op: bool) -> tuple[Pos, str] | None:
        """Compute a motion target ``(pos, kind)``; None when the motion fails."""
        buf = self.buffer
        row, col = buf.cursor
        line = buf.line()
        kind = MOTIONS[key]
        if key == "h":
            if col == 0:
                return None
            return (row, max(0, col - count)), kind
        if key == "l":
            limit = len(line) if for_op else max(0, len(line) - 1)
            if col >= limit:
                return None
            return (row, min(limit, col + count)), kind
        if key in ("j", "k"):
            target = row + count if key == "j" else row - count
            if not 0 <= row + (1 if key == "j" else -1) < buf.line_count():
                return None
            target = max(0, min(buf.line_count() - 1, target))
            want = self._want_col if self._want_col is not None else col
            return (target, want), kind
        if key == "0":
            return (row, 0), kind
        if key == "^":
            return (row, first_nonblank(line)), kind
        if key == "$":
            target = min(buf.line_count() - 1, row + count - 1)
            end = len(buf.lines[target])
            return (target, end if for_op else max(0, end - 1)), kind
        if key in ("gg", "G"):
            if typed:
                target = count - 1
            else:
                target = 0 if key == "gg" else buf.line_count() - 1
            target = max(0, min(buf.line_count() - 1, target))
            return (target, first_nonblank(buf.lines[target])), kind
        flat = self._flat()
        i = buf.offset((row, col))
        fn = {"w": word_forward, "b": word_backward, "e": word_end}[key]
        for _ in range(count):
            i = fn(flat, i)
        target = buf.pos_from_offset(i)
        if key == "w" and for_op and target[0] > row:
            # Vim: "dw" on the last word of a line stops at the end of that line.
            prev = target[0] - 1
            target = (prev, len(buf.lines[prev]))
        return target, kind

    def _move(self, key: str, count: int, typed: bool) -> bool:
        result = self._motion(key, count, typed, for_op=False)
        if result is None:
            return False
        pos, _ = result
        if key in ("j", "k"):
            if self._want_col is None:
                self._want_col = self.buffer.col
            self.buffer.cursor = pos
            self.buffer.clamp()
            return True
        self._set_cursor(pos)
        if key == "$":
            self._want_col = 1 << 30
        return True

    # ----------------------------------------------------------------- operators
    def _yank(self, text: str, linewise: bool) -> None:
        self.register = Register(text, linewise)

    def _apply_linewise(self, op: str, r1: int, r2: int) -> None:
        buf = self.buffer
        r1, r2 = sorted((r1, r2))
        text = "\n".join(buf.lines[r1 : r2 + 1])
        self._yank(text, True)
        if op == "y":
            self._set_cursor((r1, buf.col if r1 == buf.row else first_nonblank(buf.lines[r1])))
            return
        buf.begin_change()
        buf.delete_lines(r1, r2)
        buf.end_change()
        row = min(r1, buf.line_count() - 1)
        self._set_cursor((row, first_nonblank(buf.lines[row])))

    def _apply_charwise(self, op: str, start: Pos, end: Pos) -> None:
        """Apply ``op`` to the half-open range ``[start, end)``."""
        buf = self.buffer
        start, end = sorted((start, end))
        if start == end:
            return
        text = buf.get_range(start, end)
        self._yank(text, False)
        if op == "d":
            buf.begin_change()
            buf.delete_range(start, end)
            buf.end_change()
        self._set_cursor(start)

    def _operate(self, op: str, key: str, count: int, typed: bool) -> None:
        result = self._motion(key, count, typed, for_op=True)
        if result is None:
            return
        target, kind = result
        cur = self.buffer.cursor
        if kind == "line":
            self._apply_linewise(op, cur[0], target[0])
            return
        start, end = sorted((cur, target))
        if kind == "incl":
            end = (end[0], min(end[1] + 1, len(self.buffer.lines[end[0]])))
        elif end[0] > start[0] and end[1] == 0:
            # Exclusive motion ending at column 0 stops at the end of the previous line.
            end = (end[0] - 1, len(self.buffer.lines[end[0] - 1]))
        self._apply_charwise(op, start, end)

    def _put(self, after: bool, count: int) -> None:
        reg = self.register
        if not reg.text and not reg.linewise:
            return
        buf = self.buffer
        buf.begin_change()
        if reg.linewise:
            lines = reg.text.split("\n") * count
            row = buf.row + 1 if after else buf.row
            buf.insert_lines(row, lines)
            buf.end_change()
            self._set_cursor((row, first_nonblank(buf.lines[row])))
            return
        row, col = buf.cursor
        if after and buf.lines[row]:
            col += 1
        end = buf.insert_text((row, col), reg.text * count)
        buf.end_change()
        last = (end[0], max(0, end[1] - 1))
        self._set_cursor(last if "\n" not in reg.text else (row, col))

    def _enter_insert(self, key: str) -> None:
        buf = self.buffer
        buf.begin_change()
        row, col = buf.cursor
        line = buf.line()
        self.mode = Mode.INSERT
        if key == "a":
            col = min(len(line), col + 1)
        elif key == "I":
            col = len(line) - len(line.lstrip(" \t"))
        elif key == "A":
            col = len(line)
        elif key in ("o", "O"):
            indent = line[: len(line) - len(line.lstrip(" \t"))]
            new_row = row + 1 if key == "o" else row
            buf.insert_lines(new_row, [indent])
            row, col = new_row, len(indent)
        self._set_cursor((row, col))

    # ----------------------------------------------------------------- NORMAL
    def _normal_key(self, key: str) -> None:
        if not self._op and not self._g:
            self.last_message = ""
        key = ARROWS.get(key, key)
        if key == "<Esc>":
            self._reset_pending()
            return
        # Counts: "0" is a motion unless a count is already being typed.
        if key.isdigit() and len(key) == 1 and not self._g:
            if self._op:
                if key != "0" or self._op_count:
                    self._op_count += key
                    return
            elif key != "0" or self._count:
                self._count += key
                return
        if self._g:
            self._g = False
            key = "g" + key
        elif key == "g":
            self._g = True
            return
        count, typed = self._take_count()

        if self._op:
            op = self._op
            self._reset_pending()
            if key == op:
                row = self.buffer.row
                last = min(row + count - 1, self.buffer.line_count() - 1)
                self._apply_linewise(op, row, last)
            elif key in MOTIONS:
                self._operate(op, key, count, typed)
            return

        self._reset_pending()
        if key in MOTIONS:
            self._move(key, count, typed)
        elif key in ("d", "y"):
            self._count = str(count) if typed else ""
            self._op = key
        elif key == "x":
            line = self.buffer.line()
            row, col = self.buffer.cursor
            if line:
                self._apply_charwise("d", (row, col), (row, min(len(line), col + count)))
        elif key in ("p", "P"):
            self._put(key == "p", count)
        elif key == "u":
            for _ in range(count):
                if not self.buffer.undo():
                    self.last_message = "Already at oldest change"
                    break
            self.buffer.clamp()
        elif key == "<C-r>":
            for _ in range(count):
                if not self.buffer.redo():
                    self.last_message = "Already at newest change"
                    break
            self.buffer.clamp()
        elif key in ("i", "a", "I", "A", "o", "O"):
            self._enter_insert(key)
        elif key in ("v", "V"):
            self._anchor = self.buffer.cursor
            self.mode = Mode.VISUAL if key == "v" else Mode.VISUAL_LINE
        elif key == ":":
            self.mode = Mode.COMMAND
            self.cmdline = ""
        elif key == "/":
            self.mode = Mode.SEARCH
            self.cmdline = ""
        elif key in ("n", "N"):
            if self.last_search is None:
                self.last_message = "E35: No previous regular expression"
            else:
                for _ in range(count):
                    if not self._search(self.last_search, forward=key == "n"):
                        break

    # ----------------------------------------------------------------- INSERT
    def _insert_key(self, key: str) -> None:
        buf = self.buffer
        row, col = buf.cursor
        if key == "<Esc>":
            self.mode = Mode.NORMAL
            buf.end_change()
            self._set_cursor((row, max(0, col - 1)))
        elif key == "<CR>":
            line = buf.line()
            full_indent = len(line) - len(line.lstrip(" \t"))
            indent = line[: min(col, full_indent)]
            self._set_cursor(buf.split_line((row, col), indent))
        elif key == "<BS>":
            if col > 0:
                buf.delete_range((row, col - 1), (row, col))
                self._set_cursor((row, col - 1))
            elif row > 0:
                self._set_cursor(buf.join_lines(row - 1))
        elif key == "<Del>":
            if col < len(buf.line()):
                buf.delete_range((row, col), (row, col + 1))
            else:
                buf.join_lines(row)
        elif key == "<Tab>":
            self._set_cursor(buf.insert_text((row, col), TAB_SPACES))
        elif key in ARROWS:
            if key in ("<Up>", "<Down>"):
                target = row + (1 if key == "<Down>" else -1)
                if 0 <= target < buf.line_count():
                    self._set_cursor((target, col))
            else:
                self._set_cursor((row, col + (1 if key == "<Right>" else -1)))
        elif len(key) == 1 and key.isprintable():
            self._set_cursor(buf.insert_text((row, col), key))

    # ----------------------------------------------------------------- VISUAL
    def _visual_key(self, key: str) -> None:
        key = ARROWS.get(key, key)
        if key == "<Esc>":
            self.mode = Mode.NORMAL
            self._reset_pending()
            self.buffer.clamp()
            return
        if key.isdigit() and len(key) == 1 and not self._g and (key != "0" or self._count):
            self._count += key
            return
        if self._g:
            self._g = False
            key = "g" + key
        elif key == "g":
            self._g = True
            return
        count, typed = self._take_count()
        self._reset_pending()
        if key in MOTIONS:
            self._move(key, count, typed)
        elif key in ("v", "V"):
            target = Mode.VISUAL if key == "v" else Mode.VISUAL_LINE
            self.mode = Mode.NORMAL if self.mode is target else target
        elif key in ("d", "x", "y"):
            rng = self.visual_range()
            assert rng is not None
            start, end, linewise = rng
            op = "y" if key == "y" else "d"
            self.mode = Mode.NORMAL
            if linewise:
                self._apply_linewise(op, start[0], end[0])
            else:
                if end[1] + 1 > len(self.buffer.lines[end[0]]) and end[0] < len(self.lines) - 1:
                    end = (end[0] + 1, 0)  # selection covers an empty line: take its newline
                else:
                    end = (end[0], end[1] + 1)
                self._apply_charwise(op, start, end)
            self.buffer.clamp()

    # ----------------------------------------------------------------- COMMAND / SEARCH
    def _line_key(self, key: str) -> None:
        if key == "<Esc>":
            self.mode = Mode.NORMAL
            self.cmdline = ""
        elif key == "<BS>":
            if not self.cmdline:
                self.mode = Mode.NORMAL
            else:
                self.cmdline = self.cmdline[:-1]
        elif key == "<CR>":
            line, mode = self.cmdline, self.mode
            self.mode = Mode.NORMAL
            self.cmdline = ""
            if mode is Mode.COMMAND:
                self._run_command(line.strip())
            else:
                pattern = line or self.last_search
                if not pattern:
                    self.last_message = "E35: No previous regular expression"
                    return
                self.last_search = pattern
                self._search(pattern, forward=True)
        elif key == "<Tab>":
            self.cmdline += " "
        elif len(key) == 1 and key.isprintable():
            self.cmdline += key

    def _run_command(self, cmd: str) -> None:
        if not cmd:
            return
        if cmd == "set" or cmd.startswith("set "):
            return
        if self.on_command is not None:
            self.on_command(cmd)

    def _search(self, pattern: str, forward: bool) -> bool:
        """Literal, case-sensitive, wrapping search from the cursor. Returns success."""
        flat = self._flat()
        here = self.buffer.offset(self.buffer.cursor)
        wrapped = False
        if forward:
            i = flat.find(pattern, here + 1)
            if i < 0:
                i = flat.find(pattern)
                wrapped = True
        else:
            i = flat.rfind(pattern, 0, here + len(pattern) - 1)
            if i < 0:
                i = flat.rfind(pattern)
                wrapped = True
        if i < 0:
            self.last_message = f"E486: Pattern not found: {pattern}"
            return False
        self.mode = Mode.NORMAL
        self._set_cursor(self.buffer.pos_from_offset(i))
        if wrapped:
            self.last_message = (
                "search hit BOTTOM, continuing at TOP"
                if forward
                else "search hit TOP, continuing at BOTTOM"
            )
        else:
            self.last_message = "/" + pattern
        return True


def split_keys(keys: str) -> list[str]:
    """Split ``"3dw<Esc>"`` into ``["3", "d", "w", "<Esc>"]``."""
    out: list[str] = []
    i = 0
    while i < len(keys):
        if keys[i] == "<":
            j = keys.find(">", i)
            if j > i + 1 and keys[i + 1 : j].replace("-", "").isalnum():
                out.append(keys[i : j + 1])
                i = j + 1
                continue
        out.append(keys[i])
        i += 1
    return out
