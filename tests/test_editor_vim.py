"""Pure-Python, table-driven tests for the VIM state machine in coderogue.editor.vim."""

from __future__ import annotations

import pytest

from coderogue.editor.buffer import Buffer
from coderogue.editor.vim import Mode, VimEditor, split_keys


def make(text: str, cursor: tuple[int, int] = (0, 0), on_command=None) -> VimEditor:
    ed = VimEditor(Buffer(text), on_command=on_command)
    ed.cursor = cursor
    return ed


def run(text: str, keys: str, cursor: tuple[int, int] = (0, 0)) -> VimEditor:
    ed = make(text, cursor)
    ed.feed_keys(keys)
    return ed


def test_split_keys():
    assert split_keys("3dw<Esc>") == ["3", "d", "w", "<Esc>"]
    assert split_keys("a<b") == ["a", "<", "b"]
    assert split_keys("<C-r>x") == ["<C-r>", "x"]


# --------------------------------------------------------------------- motions
@pytest.mark.parametrize(
    "text, start, keys, expected",
    [
        # h j k l and counts
        ("hello", (0, 2), "h", (0, 1)),
        ("hello", (0, 0), "h", (0, 0)),
        ("hello", (0, 2), "l", (0, 3)),
        ("hello", (0, 4), "l", (0, 4)),
        ("hello", (0, 0), "3l", (0, 3)),
        ("hello", (0, 0), "9l", (0, 4)),
        ("a\nb\nc\nd", (0, 0), "j", (1, 0)),
        ("a\nb\nc\nd", (0, 0), "3j", (3, 0)),
        ("a\nb\nc\nd", (0, 0), "9j", (3, 0)),
        ("a\nb\nc\nd", (3, 0), "2k", (1, 0)),
        ("a\nb", (0, 0), "k", (0, 0)),
        # j/k remember the desired column across short lines
        ("abcdef\nx\nabcdef", (0, 4), "j", (1, 0)),
        ("abcdef\nx\nabcdef", (0, 4), "jj", (2, 4)),
        ("ab\nabcdef", (0, 0), "$j", (1, 5)),
        # arrows alias h j k l
        ("ab\ncd", (0, 0), "<Right><Down>", (1, 1)),
        ("ab\ncd", (1, 1), "<Left><Up>", (0, 0)),
        # 0 ^ $
        ("    foo bar", (0, 8), "0", (0, 0)),
        ("    foo bar", (0, 8), "^", (0, 4)),
        ("    foo bar", (0, 0), "$", (0, 10)),
        ("ab\ncdef\ngh", (0, 0), "2$", (1, 3)),
        ("", (0, 0), "$", (0, 0)),
        # w: word chars vs punctuation vs whitespace
        ("foo bar baz", (0, 0), "w", (0, 4)),
        ("foo bar baz", (0, 0), "2w", (0, 8)),
        ("foo.bar baz", (0, 0), "w", (0, 3)),
        ("foo.bar baz", (0, 3), "w", (0, 4)),
        ("foo...bar", (0, 0), "w", (0, 3)),
        ("foo...bar", (0, 3), "w", (0, 6)),
        ("print(x)", (0, 0), "w", (0, 5)),
        ("foo\nbar", (0, 0), "w", (1, 0)),
        ("foo\n    bar", (0, 1), "w", (1, 4)),
        ("foo\n\nbar", (0, 0), "w", (1, 0)),  # empty line is a word
        ("foo\n\nbar", (1, 0), "w", (2, 0)),
        ("foo bar", (0, 4), "w", (0, 6)),  # last word: stops at last char
        ("x = 1", (0, 0), "3w", (0, 4)),
        # e
        ("foo bar", (0, 0), "e", (0, 2)),
        ("foo bar", (0, 2), "e", (0, 6)),
        ("foo.bar", (0, 0), "e", (0, 2)),
        ("foo.bar", (0, 2), "e", (0, 3)),
        ("foo bar baz", (0, 0), "2e", (0, 6)),
        ("foo\n  bar", (0, 2), "e", (1, 4)),
        # b
        ("foo bar baz", (0, 8), "b", (0, 4)),
        ("foo bar baz", (0, 9), "b", (0, 8)),
        ("foo bar baz", (0, 8), "2b", (0, 0)),
        ("foo.bar", (0, 4), "b", (0, 3)),
        ("foo\nbar", (1, 0), "b", (0, 0)),
        ("foo\n\nbar", (2, 0), "b", (1, 0)),
        ("  foo", (0, 2), "b", (0, 0)),
        ("abc", (0, 0), "b", (0, 0)),
        # gg G with and without counts
        ("a\n  b\nc", (0, 0), "G", (2, 0)),
        ("a\n  b\nc", (2, 0), "gg", (0, 0)),
        ("a\n  b\nc", (0, 0), "2G", (1, 2)),
        ("a\n  b\nc", (0, 0), "2gg", (1, 2)),
        ("a\nb\nc", (0, 0), "99G", (2, 0)),
    ],
)
def test_motions(text, start, keys, expected):
    ed = run(text, keys, start)
    assert ed.cursor == expected
    assert ed.text == text  # motions never edit
    assert ed.mode is Mode.NORMAL


# --------------------------------------------------------------------- operators
@pytest.mark.parametrize(
    "text, start, keys, expected_text, expected_cursor",
    [
        # x with counts and clamping
        ("hello", (0, 0), "x", "ello", (0, 0)),
        ("hello", (0, 1), "3x", "ho", (0, 1)),
        ("hello", (0, 3), "5x", "hel", (0, 2)),
        ("hello", (0, 4), "x", "hell", (0, 3)),
        ("", (0, 0), "x", "", (0, 0)),
        # dd / counts
        ("a\nb\nc\nd", (1, 0), "dd", "a\nc\nd", (1, 0)),
        ("a\nb\nc\nd", (0, 0), "2dd", "c\nd", (0, 0)),
        ("a\nb\nc\nd", (3, 0), "dd", "a\nb\nc", (2, 0)),
        ("a\nb\nc", (1, 0), "5dd", "a", (0, 0)),
        ("only", (0, 2), "dd", "", (0, 0)),
        ("a\n    b\nc", (0, 0), "dd", "    b\nc", (0, 4)),
        # d{motion} charwise
        ("foo bar baz", (0, 0), "dw", "bar baz", (0, 0)),
        ("foo bar baz", (0, 0), "2dw", "baz", (0, 0)),
        ("foo bar baz", (0, 0), "d2w", "baz", (0, 0)),
        ("foo bar\nbaz", (0, 4), "dw", "foo \nbaz", (0, 3)),
        ("foo bar baz", (0, 0), "de", " bar baz", (0, 0)),
        ("foo bar baz", (0, 8), "db", "foo baz", (0, 4)),
        ("foo bar", (0, 4), "d0", "bar", (0, 0)),
        ("foo bar", (0, 4), "d$", "foo ", (0, 3)),
        ("foo bar", (0, 2), "dl", "fo bar", (0, 2)),
        ("foo bar", (0, 2), "dh", "fo bar", (0, 1)),
        ("foo bar", (0, 0), "dh", "foo bar", (0, 0)),
        ("abc", (0, 2), "dl", "ab", (0, 1)),
        ("foo\nbar", (1, 0), "db", "\nbar", (0, 0)),
        # d{motion} linewise
        ("a\nb\nc\nd", (1, 0), "dj", "a\nd", (1, 0)),
        ("a\nb\nc\nd", (2, 0), "dk", "a\nd", (1, 0)),
        ("a\nb\nc\nd", (1, 0), "dG", "a", (0, 0)),
        ("a\nb\nc\nd", (2, 0), "dgg", "d", (0, 0)),
        ("a\nb", (1, 0), "dj", "a\nb", (1, 0)),  # j fails on last line: no-op
        # Escape / unknown key cancels an operator
        ("abc", (0, 0), "d<Esc>x", "bc", (0, 0)),
        ("abc", (0, 0), "dzx", "bc", (0, 0)),
    ],
)
def test_delete_operators(text, start, keys, expected_text, expected_cursor):
    ed = run(text, keys, start)
    assert ed.text == expected_text
    assert ed.cursor == expected_cursor
    assert ed.pending == ""


@pytest.mark.parametrize(
    "text, start, keys, reg_text, linewise, cursor",
    [
        ("foo bar", (0, 0), "yw", "foo ", False, (0, 0)),
        ("foo bar", (0, 4), "yb", "foo ", False, (0, 0)),
        ("foo bar", (0, 0), "ye", "foo", False, (0, 0)),
        ("foo bar", (0, 4), "y$", "bar", False, (0, 4)),
        ("foo bar", (0, 4), "y0", "foo ", False, (0, 0)),
        ("foo bar", (0, 1), "yl", "o", False, (0, 1)),
        ("foo bar", (0, 1), "yh", "f", False, (0, 0)),
        ("a\nb\nc", (0, 0), "yy", "a", True, (0, 0)),
        ("a\nb\nc", (0, 0), "3yy", "a\nb\nc", True, (0, 0)),
        ("a\nb\nc", (0, 0), "yj", "a\nb", True, (0, 0)),
        ("a\nb\nc", (2, 0), "yk", "b\nc", True, (1, 0)),
        ("a\nb\nc", (1, 0), "yG", "b\nc", True, (1, 0)),
        ("a\nb\nc", (1, 0), "ygg", "a\nb", True, (0, 0)),
    ],
)
def test_yank_operators(text, start, keys, reg_text, linewise, cursor):
    ed = run(text, keys, start)
    assert ed.text == text
    assert ed.register.text == reg_text
    assert ed.register.linewise is linewise
    assert ed.cursor == cursor


def test_delete_fills_register():
    ed = run("a\nb\nc", "dd")
    assert (ed.register.text, ed.register.linewise) == ("a", True)
    ed = run("hello", "2x")
    assert (ed.register.text, ed.register.linewise) == ("he", False)


# --------------------------------------------------------------------- put
@pytest.mark.parametrize(
    "text, start, keys, expected_text, expected_cursor",
    [
        ("a\nb\nc", (0, 0), "yyp", "a\na\nb\nc", (1, 0)),
        ("a\nb\nc", (1, 0), "yyP", "a\nb\nb\nc", (1, 0)),
        ("a\nb\nc", (0, 0), "ddp", "b\na\nc", (1, 0)),
        ("a\nb\nc", (0, 0), "yy3p", "a\na\na\na\nb\nc", (1, 0)),
        ("a\n  b", (1, 0), "yykp", "a\n  b\n  b", (1, 2)),
        ("abc", (0, 0), "xp", "bac", (0, 1)),
        ("abc", (0, 0), "xP", "abc", (0, 0)),
        ("foo bar", (0, 0), "yw$p", "foo barfoo ", (0, 10)),
        ("foo bar", (0, 4), "yw0P", "barfoo bar", (0, 2)),
        ("ab", (0, 0), "yl2p", "aaab", (0, 2)),
        ("", (0, 0), "p", "", (0, 0)),  # empty register: no-op
    ],
)
def test_put(text, start, keys, expected_text, expected_cursor):
    ed = run(text, keys, start)
    assert ed.text == expected_text
    assert ed.cursor == expected_cursor


def test_put_charwise_into_empty_line():
    ed = run("abc\n", "yw" + "jp")
    assert ed.text == "abc\nabc"


# --------------------------------------------------------------------- insert
@pytest.mark.parametrize(
    "text, start, keys, expected_text, expected_cursor",
    [
        ("abc", (0, 1), "iXY<Esc>", "aXYbc", (0, 2)),
        ("abc", (0, 1), "aXY<Esc>", "abXYc", (0, 3)),
        ("  abc", (0, 4), "IX<Esc>", "  Xabc", (0, 2)),
        ("abc", (0, 0), "AXY<Esc>", "abcXY", (0, 4)),
        ("abc", (0, 0), "i<Esc>", "abc", (0, 0)),
        ("abc", (0, 2), "i<Esc>", "abc", (0, 1)),
        ("", (0, 0), "ahi<Esc>", "hi", (0, 1)),
        ("a\nb", (0, 0), "onew<Esc>", "a\nnew\nb", (1, 2)),
        ("a\nb", (1, 0), "Onew<Esc>", "a\nnew\nb", (1, 2)),
        ("    a", (0, 4), "ob<Esc>", "    a\n    b", (1, 4)),
        ("    a", (0, 4), "Ob<Esc>", "    b\n    a", (0, 4)),
        # <CR> splits and keeps indentation
        ("    if x:", (0, 0), "A<CR>pass<Esc>", "    if x:\n    pass", (1, 7)),
        ("abcdef", (0, 2), "i<CR><Esc>", "ab\ncdef", (1, 0)),
        ("  abcd", (0, 4), "i<CR><Esc>", "  ab\n  cd", (1, 1)),
        # <BS> deletes, joins at column 0
        ("abc", (0, 2), "a<BS><Esc>", "ab", (0, 1)),
        ("ab\ncd", (1, 0), "i<BS><Esc>", "abcd", (0, 1)),
        ("abc", (0, 0), "i<BS><Esc>", "abc", (0, 0)),
        # <Tab> inserts four spaces
        ("x", (0, 0), "i<Tab><Esc>", "    x", (0, 3)),
        # typed punctuation and spaces
        ("", (0, 0), "iprint('hi there')<Esc>", "print('hi there')", (0, 16)),
        # digits are text in INSERT, not counts
        ("", (0, 0), "i3dd<Esc>", "3dd", (0, 2)),
    ],
)
def test_insert(text, start, keys, expected_text, expected_cursor):
    ed = run(text, keys, start)
    assert ed.text == expected_text
    assert ed.cursor == expected_cursor
    assert ed.mode is Mode.NORMAL


def test_insert_mode_cursor_may_sit_at_end_of_line():
    ed = run("abc", "A")
    assert ed.mode is Mode.INSERT
    assert ed.cursor == (0, 3)
    ed.feed_key("<Esc>")
    assert ed.cursor == (0, 2)


def test_insert_arrows_move_without_leaving_insert():
    ed = run("ab\ncd", "i<Right><Right><Down>X<Esc>")
    assert ed.text == "ab\ncdX"


# --------------------------------------------------------------------- undo / redo
@pytest.mark.parametrize(
    "text, keys",
    [
        ("hello", "x"),
        ("hello", "3x"),
        ("a\nb\nc", "dd"),
        ("a\nb\nc", "dG"),
        ("foo bar", "dw"),
        ("a\nb", "yyp"),
        ("abc", "ifoo<Esc>"),
        ("abc", "ofoo<CR>bar<Esc>"),
        ("one two", "vey$p"),
        ("a\nb\nc", "Vjd"),
    ],
)
def test_undo_redo_round_trip(text, keys):
    ed = run(text, keys)
    after = ed.text
    assert after != text
    ed.feed_key("u")
    assert ed.text == text
    ed.feed_key("<C-r>")
    assert ed.text == after
    ed.feed_key("u")
    assert ed.text == text


def test_insert_session_is_one_undo_step():
    ed = run("", "ione<CR>two<CR>three<Esc>")
    assert ed.text == "one\ntwo\nthree"
    ed.feed_key("u")
    assert ed.text == ""
    assert ed.cursor == (0, 0)


def test_multiple_undos_and_messages():
    ed = run("abcd", "xxx")
    assert ed.text == "d"
    ed.feed_keys("2u")
    assert ed.text == "bcd"
    ed.feed_keys("uu")
    assert ed.text == "abcd"
    assert ed.last_message == "Already at oldest change"
    ed.feed_keys("3<C-r>")
    assert ed.text == "d"
    ed.feed_key("<C-r>")
    assert ed.last_message == "Already at newest change"


def test_motions_and_yanks_do_not_create_undo_steps():
    ed = run("abc\ndef", "jwyy0")
    assert not ed.buffer.can_undo
    ed = run("abc", "i<Esc>")
    assert not ed.buffer.can_undo


def test_undo_clamps_cursor():
    ed = run("abc", "A123<Esc>")
    assert ed.cursor == (0, 5)
    ed.feed_key("u")
    assert ed.cursor[1] <= 2


# --------------------------------------------------------------------- VISUAL
@pytest.mark.parametrize(
    "text, start, keys, expected_text, expected_cursor, reg",
    [
        ("hello world", (0, 0), "vlld", "lo world", (0, 0), "hel"),
        ("hello world", (0, 0), "vex", " world", (0, 0), "hello"),
        ("hello world", (0, 6), "vbd", "orld", (0, 0), "hello w"),
        ("hello world", (0, 4), "vhhd", "he world", (0, 2), "llo"),
        ("ab\ncd\nef", (0, 1), "vjd", "a\nef", (0, 0), "b\ncd"),
        ("a\nb\nc\nd", (1, 0), "Vjd", "a\nd", (1, 0), "b\nc"),
        ("a\nb\nc\nd", (1, 0), "Vkx", "c\nd", (0, 0), "a\nb"),
        ("a\nb\nc", (0, 0), "VGd", "", (0, 0), "a\nb\nc"),
        ("abc\n\ndef", (1, 0), "vd", "abc\ndef", (1, 0), "\n"),
    ],
)
def test_visual_delete(text, start, keys, expected_text, expected_cursor, reg):
    ed = run(text, keys, start)
    assert ed.text == expected_text
    assert ed.cursor == expected_cursor
    assert ed.register.text == reg
    assert ed.mode is Mode.NORMAL


def test_visual_yank_and_put():
    ed = run("foo bar", "vey")
    assert ed.mode is Mode.NORMAL
    assert ed.register.text == "foo"
    assert ed.register.linewise is False
    ed.feed_keys("$p")
    assert ed.text == "foo barfoo"
    ed = run("a\nb", "Vyp")
    assert ed.text == "a\na\nb"


def test_visual_range_and_escape():
    ed = run("hello\nworld", "lvjl", (0, 0))
    assert ed.mode is Mode.VISUAL
    assert ed.visual_range() == ((0, 1), (1, 2), False)
    ed.feed_key("V")
    assert ed.mode is Mode.VISUAL_LINE
    assert ed.visual_range() == ((0, 0), (1, 5), True)
    ed.feed_key("<Esc>")
    assert ed.mode is Mode.NORMAL
    assert ed.visual_range() is None
    assert ed.text == "hello\nworld"


def test_visual_backwards_selection_is_ordered():
    ed = run("abcdef", "vhhh", (0, 4))
    assert ed.visual_range() == ((0, 1), (0, 4), False)


def test_visual_counts_and_toggle():
    ed = run("a b c d", "v2wd")
    assert ed.text == " d"
    ed = run("abc", "vv")
    assert ed.mode is Mode.NORMAL


# --------------------------------------------------------------------- COMMAND
def test_command_callback_fires_and_returns_to_normal():
    seen: list[str] = []
    ed = make("x", on_command=seen.append)
    ed.feed_keys(":w")
    assert ed.mode is Mode.COMMAND
    assert ed.cmdline == "w"
    ed.feed_key("<CR>")
    assert seen == ["w"]
    assert ed.mode is Mode.NORMAL
    assert ed.cmdline == ""


@pytest.mark.parametrize(
    "keys, expected",
    [
        (":wq<CR>", ["wq"]),
        (":hint<CR>", ["hint"]),
        (":lang python<CR>", ["lang python"]),
        (":skp<BS><BS>kip<CR>", ["skip"]),
        (":q<Esc>", []),
        (":<BS>", []),
        (":set number<CR>", []),
        (":<CR>", []),
        (":  help  <CR>", ["help"]),
    ],
)
def test_command_lines(keys, expected):
    seen: list[str] = []
    ed = make("x", on_command=seen.append)
    ed.feed_keys(keys)
    assert seen == expected
    assert ed.mode is Mode.NORMAL


def test_command_without_callback_is_harmless():
    ed = run("abc", ":w<CR>x")
    assert ed.text == "bc"


# --------------------------------------------------------------------- SEARCH
def test_search_forward_wraps_and_repeats():
    ed = make("foo bar\nbaz foo\nfoo")
    ed.feed_keys("/foo")
    assert ed.mode is Mode.SEARCH
    assert ed.cmdline == "foo"
    ed.feed_key("<CR>")
    assert ed.mode is Mode.NORMAL
    assert ed.cursor == (1, 4)
    assert ed.last_search == "foo"
    ed.feed_key("n")
    assert ed.cursor == (2, 0)
    ed.feed_key("n")
    assert ed.cursor == (0, 0)
    assert "BOTTOM" in ed.last_message
    ed.feed_key("N")
    assert ed.cursor == (2, 0)
    ed.feed_key("N")
    assert ed.cursor == (1, 4)


def test_search_is_case_sensitive_and_reports_missing():
    ed = make("Foo foo")
    ed.feed_keys("/Foo<CR>")
    assert ed.cursor == (0, 0)
    ed.feed_keys("/FOO<CR>")
    assert ed.cursor == (0, 0)
    assert ed.last_message == "E486: Pattern not found: FOO"


def test_search_empty_pattern_reuses_last_and_escape_cancels():
    ed = make("ab ab ab")
    ed.feed_keys("/ab<CR>")
    assert ed.cursor == (0, 3)
    ed.feed_keys("/<CR>")
    assert ed.cursor == (0, 6)
    ed.feed_keys("/zz<Esc>")
    assert ed.mode is Mode.NORMAL
    assert ed.cursor == (0, 6)
    assert ed.last_search == "ab"


def test_n_without_search():
    ed = run("abc", "n")
    assert ed.last_message.startswith("E35")


# --------------------------------------------------------------------- pending / misc
@pytest.mark.parametrize(
    "keys, pending",
    [("3", "3"), ("d", "d"), ("2d", "2d"), ("d3", "d3"), ("g", "g"), ("d<Esc>", ""), ("3j", "")],
)
def test_pending(keys, pending):
    ed = run("a\nb\nc\nd\ne", keys)
    assert ed.pending == pending


def test_zero_after_count_is_part_of_count():
    ed = run("a" * 20, "10l")
    assert ed.cursor == (0, 10)


def test_normal_cursor_never_past_last_char():
    ed = run("abc\nabcdef", "j$k")
    assert ed.cursor == (0, 2)
    ed.cursor = (0, 99)
    assert ed.cursor == (0, 2)


def test_set_text_resets_state():
    ed = run("abc", "x")
    ed.set_text("new\ntext")
    assert ed.text == "new\ntext"
    assert ed.cursor == (0, 0)
    assert not ed.buffer.can_undo
    assert ed.mode is Mode.NORMAL
