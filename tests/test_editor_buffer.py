"""Pure-Python tests for coderogue.editor.buffer."""

from __future__ import annotations

import subprocess
import sys

import pytest

from coderogue.editor.buffer import Buffer


def test_buffer_and_vim_do_not_import_pygame():
    code = (
        "import sys, coderogue.editor.buffer, coderogue.editor.vim; "
        "assert 'pygame' not in sys.modules"
    )
    subprocess.run([sys.executable, "-c", code], check=True)


def test_empty_buffer_has_one_line():
    b = Buffer()
    assert b.lines == [""]
    assert b.text == ""
    assert b.cursor == (0, 0)


def test_set_get_text_round_trip():
    b = Buffer("a\nb")
    b.set_text("x\ny\nz")
    assert b.lines == ["x", "y", "z"]
    assert b.get_text() == "x\ny\nz"
    b.text = "q"
    assert b.lines == ["q"]


@pytest.mark.parametrize(
    "text, pos, ins, expected, end",
    [
        ("abc", (0, 1), "XY", "aXYbc", (0, 3)),
        ("abc", (0, 3), "!", "abc!", (0, 4)),
        ("abc", (0, 1), "1\n2", "a1\n2bc", (1, 1)),
        ("abc\ndef", (1, 0), "\n", "abc\n\ndef", (2, 0)),
        ("", (0, 0), "hi\nthere\nyou", "hi\nthere\nyou", (2, 3)),
    ],
)
def test_insert_text(text, pos, ins, expected, end):
    b = Buffer(text)
    assert b.insert_text(pos, ins) == end
    assert b.text == expected


@pytest.mark.parametrize(
    "text, start, end, expected, removed",
    [
        ("abcdef", (0, 1), (0, 3), "adef", "bc"),
        ("abc\ndef", (0, 1), (1, 2), "af", "bc\nde"),
        ("abc\ndef", (0, 3), (1, 0), "abcdef", "\n"),
        ("a\nb\nc", (0, 0), (2, 1), "", "a\nb\nc"),
        ("abcdef", (0, 3), (0, 1), "adef", "bc"),  # reversed endpoints are normalised
    ],
)
def test_delete_range(text, start, end, expected, removed):
    b = Buffer(text)
    assert b.delete_range(start, end) == removed
    assert b.text == expected


def test_get_range_matches_delete():
    b = Buffer("one\ntwo\nthree")
    assert b.get_range((0, 1), (2, 2)) == "ne\ntwo\nth"


def test_split_and_join_lines():
    b = Buffer("    hello world")
    assert b.split_line((0, 10), "    ") == (1, 4)
    assert b.lines == ["    hello ", "    world"]
    assert b.join_lines(0) == (0, 10)
    assert b.lines == ["    hello     world"]
    assert b.join_lines(0) == (0, 19)  # no next line: no-op


def test_delete_all_lines_keeps_one_empty():
    b = Buffer("a\nb")
    assert b.delete_lines(0, 1) == ["a", "b"]
    assert b.lines == [""]


def test_offsets_round_trip():
    b = Buffer("ab\n\ncde")
    for pos in [(0, 0), (0, 2), (1, 0), (2, 0), (2, 3)]:
        assert b.pos_from_offset(b.offset(pos)) == pos


@pytest.mark.parametrize(
    "text, cursor, insert, expected",
    [
        ("abc", (0, 5), False, (0, 2)),
        ("abc", (0, 5), True, (0, 3)),
        ("", (0, 3), False, (0, 0)),
        ("a\nb", (9, 0), False, (1, 0)),
        ("abc", (0, -2), False, (0, 0)),
    ],
)
def test_clamp(text, cursor, insert, expected):
    b = Buffer(text)
    b.cursor = cursor
    b.clamp(insert=insert)
    assert b.cursor == expected


def test_undo_redo_snapshots():
    b = Buffer("abc")
    b.begin_change()
    b.insert_text((0, 0), "X")
    assert b.end_change() is True
    b.begin_change()
    b.delete_range((0, 0), (0, 2))
    assert b.end_change() is True
    assert b.text == "bc"
    assert b.undo() and b.text == "Xabc"
    assert b.undo() and b.text == "abc"
    assert not b.undo()
    assert b.redo() and b.text == "Xabc"
    assert b.redo() and b.text == "bc"
    assert not b.redo()


def test_noop_change_is_not_recorded():
    b = Buffer("abc")
    b.begin_change()
    assert b.end_change() is False
    assert not b.can_undo


def test_new_change_clears_redo():
    b = Buffer("abc")
    b.begin_change()
    b.insert_text((0, 0), "1")
    b.end_change()
    b.undo()
    assert b.can_redo
    b.begin_change()
    b.insert_text((0, 0), "2")
    b.end_change()
    assert not b.can_redo
