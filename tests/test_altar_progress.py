"""Progress model, puzzle-id lookup, HUD and panel helpers."""

import json

import pygame
import pytest

from coderogue.altar.lookup import resolve_puzzle_id
from coderogue.app import resource_path
from coderogue.progress import Progress, bilingual_flag
from coderogue.puzzles import load_all
from coderogue.ui.hud import draw_hud
from coderogue.ui.panels import draw_panel, live_font, wrap_text


def test_progress_solve_xp_and_bilingual():
    p = Progress()
    assert p.level == 1 and not p.is_solved("a")
    assert p.mark_solved("a", "python", xp=30) is True
    assert p.xp == 30 and p.is_solved("a") and p.is_solved("a", "python")
    assert p.mark_solved("a", "bash", xp=30) is False
    assert p.xp == 30 and p.is_bilingual("a") and bilingual_flag("a") in p.flags
    p.mark_skipped("b")
    p.mark_solved("b", "python", xp=40)
    assert p.xp == 50


def test_progress_hints_and_drafts():
    p = Progress()
    p.note_hint("a", "python", 2)
    p.note_hint("a", "python", 1)
    p.note_hint("a", "bash", 3)
    assert p.hint_rung("a", "python") == 2 and p.hints_used["a"] == 3
    p.set_draft("a", "python", "print(1)")
    assert p.draft("a", "python") == "print(1)" and p.draft("a", "bash") is None


def test_progress_round_trip_is_json_safe():
    p = Progress(xp=120, flags={"met_moth"})
    p.mark_solved("ch0-01", "python")
    p.mark_skipped("ch0-02")
    p.note_hint("ch0-02", "bash", 3)
    p.set_draft("ch0-02", "bash", 'echo "hi"\n')
    data = json.loads(json.dumps(p.to_dict()))
    q = Progress.from_dict(data)
    assert q == p and q.level == 2
    assert Progress.from_dict({}) == Progress()


def test_resolve_puzzle_ids():
    puzzles = load_all(resource_path("content", "puzzles"))
    assert resolve_puzzle_id(puzzles, "ch0-01") == "ch0-01"
    assert resolve_puzzle_id(puzzles, "P-01") == "ch0-01"
    assert resolve_puzzle_id(puzzles, "1-05") == "ch1-05"
    assert resolve_puzzle_id(puzzles, "nope") is None


@pytest.fixture
def surface():
    pygame.init()
    yield pygame.Surface((960, 540))
    pygame.quit()


class _Player:
    hp = 3
    max_hp = 6


def test_hud_and_panels_draw(surface):
    rect = draw_hud(surface, _Player(), Progress(xp=150), "NORMAL", "Test Room")
    assert rect.width > 0 and surface.get_at((rect.x + 1, rect.y + 1))[:3] != (0, 0, 0)
    draw_hud(surface, _Player(), None, "INSERT")
    draw_panel(surface, (10, 10, 50, 20), (14, 13, 18, 120))


def test_wrap_text(surface):
    font = live_font(14)
    width = font.size("x" * 20)[0]
    lines = wrap_text(font, "one two three four five six seven eight\n\n  indented", width)
    assert all(font.size(line)[0] <= width for line in lines)
    assert "" in lines and lines[-1].startswith("  ")
    assert wrap_text(font, "a" * 50, width) == ["a" * 20, "a" * 20, "a" * 10]
