"""Headless tests for the pygame side of the editor: highlighter, view, key translation."""

from __future__ import annotations

from pathlib import Path

import pygame
import pytest

from coderogue.editor.buffer import Buffer
from coderogue.editor.highlight import tokenize_line
from coderogue.editor.keys import KeyRepeater, KeyTranslator, translate_event
from coderogue.editor.render import EditorTheme, EditorView
from coderogue.editor.vim import Mode, VimEditor

FONT = (
    Path(__file__).resolve().parent.parent / "assets/fonts/JetBrainsMono/JetBrainsMono-Regular.ttf"
)

SAMPLES = {
    "python": 'def greet(name):\n    # say hi\n    print(f"hi {name}", 42)\n' * 20,
    "bash": 'for i in 1 2 3; do\n  echo "n=$i" # count\ndone\n' * 20,
    "powershell": 'foreach ($x in 1..3) {\n  Write-Output "$x" # loop\n}\n' * 20,
    None: "plain text " * 30,
}


@pytest.fixture(scope="module")
def font():
    pygame.font.init()
    yield pygame.font.Font(str(FONT), 14)


@pytest.mark.parametrize("language", list(SAMPLES))
@pytest.mark.parametrize("keys", ["", "Gi", "vjj", "Vj", ":wq", "/hi"])
def test_render_smoke(font, language, keys):
    ed = VimEditor(Buffer(SAMPLES[language]))
    ed.feed_keys("10j$" + keys)
    view = EditorView(ed, font, language=language)
    view.error_lines = {1, 11}
    surface = pygame.Surface((320, 200))
    view.draw(surface, pygame.Rect(8, 8, 300, 180), EditorTheme())
    rows = view.visible_rows(pygame.Rect(8, 8, 300, 180))
    assert view.scroll_row <= ed.cursor[0] < view.scroll_row + rows
    assert surface.get_at((10, 10))[:3] != (0, 0, 0)  # gutter got painted


def test_render_message_and_default_theme(font):
    ed = VimEditor(Buffer("abc"))
    ed.feed_keys("/zzz<CR>")
    view = EditorView(ed, font)
    surface = pygame.Surface((200, 80))
    view.draw(surface, pygame.Rect(0, 0, 200, 80))
    assert ed.last_message.startswith("E486")


@pytest.mark.parametrize(
    "line, language, expected",
    [
        ("def f(): # hi", "python", [("def", "keyword"), ("# hi", "comment")]),
        ("x = 'a\\'b' + 12", "python", [("'a\\'b'", "string"), ("12", "number")]),
        ("print(len(x))", "python", [("print", "builtin"), ("len", "builtin")]),
        ('echo "$HOME" # c', "bash", [("echo", "builtin"), ('"$HOME"', "string")]),
        ("if [ $n -gt 3 ]; then", "bash", [("if", "keyword"), ("$n", "variable")]),
        ("echo $#", "bash", [("$#", "variable")]),
        ("Write-Host $name", "powershell", [("Write-Host", "builtin"), ("$name", "variable")]),
        ("if ($a -eq 1) { }", "powershell", [("if", "keyword"), ("-eq", "keyword")]),
    ],
)
def test_tokenizer(line, language, expected):
    tokens = tokenize_line(line, language)
    assert "".join(text for text, _ in tokens) == line
    for token in expected:
        assert token in tokens


def test_tokenizer_plain_and_empty():
    assert tokenize_line("abc def", None) == [("abc def", "text")]
    assert tokenize_line("", "python") == []


# --------------------------------------------------------------------- keys
def keydown(key: int, unicode: str = "", mod: int = 0) -> pygame.event.Event:
    return pygame.event.Event(pygame.KEYDOWN, key=key, unicode=unicode, mod=mod)


def textinput(text: str) -> pygame.event.Event:
    return pygame.event.Event(pygame.TEXTINPUT, text=text)


@pytest.mark.parametrize(
    "event, mode, expected",
    [
        (keydown(pygame.K_ESCAPE), Mode.INSERT, "<Esc>"),
        (keydown(pygame.K_RETURN), Mode.COMMAND, "<CR>"),
        (keydown(pygame.K_BACKSPACE), Mode.INSERT, "<BS>"),
        (keydown(pygame.K_TAB), Mode.INSERT, "<Tab>"),
        (keydown(pygame.K_r, "\x12", pygame.KMOD_LCTRL), Mode.NORMAL, "<C-r>"),
        (keydown(pygame.K_LEFT), Mode.NORMAL, "<Left>"),
        (keydown(pygame.K_DOWN), Mode.INSERT, "<Down>"),
        (keydown(pygame.K_h, "h"), Mode.NORMAL, "h"),
        (keydown(pygame.K_4, "$"), Mode.VISUAL, "$"),
        (keydown(pygame.K_h, "h"), Mode.INSERT, None),
        (textinput("h"), Mode.INSERT, "h"),
        (textinput("h"), Mode.NORMAL, None),
        (textinput("/"), Mode.SEARCH, "/"),
    ],
)
def test_translate_event(event, mode, expected):
    assert translate_event(event, mode) == expected


def test_translator_swallows_textinput_echo():
    ed = VimEditor(Buffer("abc"))
    tr = KeyTranslator()
    stream = [keydown(pygame.K_i, "i"), textinput("i"), keydown(pygame.K_x, "x"), textinput("x")]
    for event in stream:
        for key in tr.translate(event, ed.mode):
            ed.feed_key(key)
    assert ed.mode is Mode.INSERT
    assert ed.text == "xabc"


def test_arrows_drive_editor():
    ed = VimEditor(Buffer("ab\ncd"))
    tr = KeyTranslator()
    for event in [keydown(pygame.K_DOWN), keydown(pygame.K_RIGHT)]:
        for key in tr.translate(event, ed.mode):
            ed.feed_key(key)
    assert ed.cursor == (1, 1)


def test_key_repeater_timing():
    rep = KeyRepeater()
    rep.press(pygame.K_j, "j")
    assert rep.update(0.300) == []
    assert rep.update(0.060) == ["j"]  # 360 ms: past the 350 ms delay
    assert rep.update(0.040) == ["j"]
    assert len(rep.update(0.100)) == 2
    rep.release(pygame.K_j)
    assert rep.update(1.0) == []


def test_key_repeater_ignores_non_motions_and_other_modes():
    rep = KeyRepeater()
    rep.press(pygame.K_x, "x")
    assert rep.held is None
    rep.press(pygame.K_j, "j", Mode.INSERT)
    assert rep.held is None
    rep.press(pygame.K_l, "l")
    assert rep.update(1.0, Mode.VISUAL) == []
    assert rep.held is None
