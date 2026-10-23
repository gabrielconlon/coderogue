from pathlib import Path

import pygame
import pytest

from coderogue.app import Game, letterbox_rect, resource_path
from coderogue.input.modes import Mode
from coderogue.scene import Scene
from coderogue.world.scene import WorldScene

ROOT = Path(__file__).resolve().parent.parent
TEST_ROOM = ROOT / "content" / "maps" / "test_room.tmj"


@pytest.fixture
def game():
    g = Game(headless=True)
    yield g
    pygame.quit()


def key(k, uni=""):
    return pygame.event.Event(pygame.KEYDOWN, key=k, unicode=uni, mod=0)


def test_resource_path_and_letterbox():
    assert resource_path("content", "maps", "test_room.tmj").exists()
    assert letterbox_rect((960, 540), (960, 540)) == (0, 0, 960, 540)
    assert letterbox_rect((2000, 1200), (960, 540)) == (40, 60, 1920, 1080)
    x, y, w, h = letterbox_rect((800, 600), (960, 540))
    assert w == 800 and y > 0


def test_scene_stack(game):
    a, b, c = Scene(game), Scene(game), Scene(game)
    game.push(a)
    game.push(b)
    assert game.scene is b
    game.replace(c)
    assert game.scene is c and game.scenes == [a, c]
    assert game.pop() is c
    assert game.scene is a


def test_world_spawns_and_moves(game):
    ws = WorldScene(game, TEST_ROOM)
    game.push(ws)
    assert len(ws.enemies) == 2 and len(ws.altars) == 1
    x0 = ws.player.x
    ws.handle_event(key(pygame.K_l, "l"))
    for _ in range(30):
        game.step()
    assert ws.player.x > x0
    ws.handle_event(pygame.event.Event(pygame.KEYUP, key=pygame.K_l, mod=0))
    assert ws.move_vector() == (0, 0)


def test_count_prefix_dashes(game):
    game.dev_all_unlocked = True  # counts are taught by Tally's letter in Chapter 2
    ws = WorldScene(game, TEST_ROOM)
    game.push(ws)
    y0 = ws.player.y
    ws.handle_event(key(pygame.K_2, "2"))
    assert ws.modes.pending_count == 2
    ws.handle_event(key(pygame.K_j, "j"))
    assert ws.modes.pending_count is None
    assert ws.player.dashing
    for _ in range(30):
        game.step()
    assert ws.player.y == pytest.approx(y0 + 32, abs=0.01)


def test_count_attack_and_command_quit(game):
    game.dev_all_unlocked = True  # counts are taught by Tally's letter in Chapter 2
    ws = WorldScene(game, TEST_ROOM)
    game.push(ws)
    ws.handle_event(key(pygame.K_3, "3"))
    ws.handle_event(key(pygame.K_x, "x"))
    assert ws.player.attacking and ws.player.queued_strikes == 2
    ws.handle_event(key(pygame.K_SEMICOLON, ":"))
    assert ws.modes.mode is Mode.COMMAND
    game.running = True
    for ch, k in (("q", pygame.K_q),):
        ws.handle_event(key(k, ch))
    ws.handle_event(key(pygame.K_RETURN, "\r"))
    assert ws.modes.mode is Mode.NORMAL
    assert not game.running


def test_altar_interact(game):
    ws = WorldScene(game, TEST_ROOM)
    game.push(ws)
    seen = []
    ws.altar_handler = seen.append
    ws.handle_event(key(pygame.K_i, "i"))
    assert seen == []
    altar = ws.altars[0]
    ws.player.place_center(*altar.center)
    ws.handle_event(key(pygame.K_i, "i"))
    assert seen == [altar]


def test_attack_kills_enemy(game):
    ws = WorldScene(game, TEST_ROOM)
    game.push(ws)
    enemy = ws.enemies[0]
    enemy.speed = 0
    enemy.direction = (0, 0)
    enemy.turn_timer = 99
    ws.player.place_center(enemy.center[0] - 16, enemy.center[1])
    ws.player.facing = (1, 0)
    ws.player.iframes = 99  # ignore contact damage
    for _ in range(enemy.max_hp):
        enemy.place_center(ws.player.center[0] + 16, ws.player.center[1])
        enemy.knockback_time = 0
        enemy.iframes = 0
        ws.player.attack()
        game.step()
        for _ in range(40):
            game.step()
    assert enemy not in ws.enemies


def test_draw_does_not_crash(game):
    ws = WorldScene(game, TEST_ROOM)
    game.push(ws)
    game.draw()
