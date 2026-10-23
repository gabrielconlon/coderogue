"""Scripted headless playthrough of the critical path: a new game to the end of Chapter 1.

The tests run in file order and share one Game (module fixture), like a single play
session. Long walks are replaced by ``teleport`` (setting the hero's position); everything
else goes through the real event path: INTERACT, dialogue keys, the altar editor (keys
through the KeyTranslator, ``:w`` casts), the waystone menu, ``x`` strikes, ``:save`` and
door transitions. Each map also gets one short real walk with held keys.
"""

from __future__ import annotations

import re
from pathlib import Path

import pygame
import pytest

from coderogue.altar import AltarScene
from coderogue.altar.scene import CLOSE_DELAY_S
from coderogue.app import Game, resource_path, start_world
from coderogue.editor.vim import Mode as EditorMode
from coderogue.entities.boss import Boss, Grubble
from coderogue.entities.waystone import WaystoneMenu
from coderogue.languages import available
from coderogue.story.scene import DialogueScene
from coderogue.world.scene import WorldScene
from coderogue.world.transitions import FADE_TIME

DT = 1 / 60
TILE = 16
START_MAP = resource_path("content", "maps", "little_tilde_scriptorium.tmj")


# ---- shared session -----------------------------------------------------------------------
class Session:
    game: Game
    world: WorldScene
    home: Path


@pytest.fixture(scope="module")
def s(tmp_path_factory):
    home = tmp_path_factory.mktemp("coderogue_home")
    with pytest.MonkeyPatch.context() as mp:
        mp.setenv("CODEROGUE_HOME", str(home))
        game = Game(headless=True)
        world = start_world(game, START_MAP, new=True)
        game.push(world)
        sess = Session()
        sess.game, sess.world, sess.home = game, world, home
        yield sess
    pygame.quit()


# ---- event helpers ------------------------------------------------------------------------
def keydown(code: int, uni: str = "", mod: int = 0) -> pygame.event.Event:
    return pygame.event.Event(pygame.KEYDOWN, key=code, unicode=uni, mod=mod)


def keyup(code: int) -> pygame.event.Event:
    return pygame.event.Event(pygame.KEYUP, key=code, mod=0)


def send(game: Game, *events: pygame.event.Event) -> None:
    """Deliver events the way Game.run does: always to the current top scene."""
    for event in events:
        if game.scene is not None:
            game.scene.handle_event(event)


def press(game: Game, code: int, uni: str = "") -> None:
    send(game, keydown(code, uni))


def type_text(game: Game, text: str) -> None:
    """Each character as SDL sends it: a KEYDOWN (with unicode) then its TEXTINPUT.
    ``\\n`` is the Enter key."""
    for ch in text:
        if ch == "\n":
            press(game, pygame.K_RETURN)
            continue
        code = ord(ch.lower()) if ch.isascii() else 0
        send(game, keydown(code, ch), pygame.event.Event(pygame.TEXTINPUT, text=ch))


def command(game: Game, cmd: str) -> None:
    """Type ``:cmd<CR>`` (NORMAL mode in the editor, or the world's command line)."""
    type_text(game, ":" + cmd)
    press(game, pygame.K_RETURN)


def steps(game: Game, seconds: float) -> None:
    for _ in range(round(seconds / DT)):
        game.step()


# ---- world helpers ------------------------------------------------------------------------
def tile_center(tx: int, ty: int) -> tuple[float, float]:
    return (tx * TILE + TILE / 2, ty * TILE + TILE / 2)


def teleport(world: WorldScene, tx: float, ty: float) -> None:
    """Put the hero on tile (tx, ty) directly (cross-map walking is too slow to script)."""
    world.player.place_center(*tile_center(int(tx), int(ty)))
    world.player.trail.clear()
    world.held.clear()


def walk(game: Game, world: WorldScene, key: str, seconds: float) -> tuple[float, float]:
    """Hold a movement key through handle_event for ``seconds``; return the displacement."""
    x0, y0 = world.player.center
    code = pygame.key.key_code(key)
    send(game, keydown(code, key))
    steps(game, seconds)
    send(game, keyup(code))
    game.step()
    assert not world.held
    x1, y1 = world.player.center
    return (x1 - x0, y1 - y0)


def interact(game: Game) -> None:
    """INTERACT through the real event path (``i``, then SDL's TEXTINPUT echo)."""
    send(game, keydown(pygame.K_i, "i"), pygame.event.Event(pygame.TEXTINPUT, text="i"))


def by_name(items, name: str):
    found = [e for e in items if e.name == name]
    assert found, f"no {name!r} in {[e.name for e in items]}"
    return found[0]


def _stand_near(world: WorldScene, ent, reach_fn) -> None:
    """Teleport onto ``ent``'s tile or a neighbour where only ``ent`` is in reach."""
    tx, ty = int(ent.center[0] // TILE), int(ent.center[1] // TILE)
    for dx, dy in ((0, 0), (0, 1), (0, -1), (-1, 0), (1, 0), (1, 1), (-1, 1)):
        teleport(world, tx + dx, ty + dy)
        if reach_fn() is not ent:
            continue
        others = [world.altar_in_reach(), world.waystone_in_reach(), world.chest_in_reach()]
        if all(o is None or o is ent for o in others):
            return
    raise AssertionError(f"no tile near {ent.name!r} where only it is in reach")


def advance_dialogue(game: Game) -> DialogueScene:
    """Press j until the DialogueScene pops (Enter picks the first reply at a choice)."""
    scene = game.scene
    assert isinstance(scene, DialogueScene), f"expected dialogue, got {scene!r}"
    for _ in range(400):
        if game.scene is not scene:
            break
        if scene.choosing:
            press(game, pygame.K_RETURN, "\r")
        else:
            press(game, pygame.K_j, "j")
    assert game.scene is not scene and scene.finished
    return scene


def talk(game: Game, world: WorldScene, npc_name: str) -> str:
    """Talk to an NPC through INTERACT; returns the dialogue id that played."""
    npc = by_name(world.npcs, npc_name)
    _stand_near(world, npc, world.npc_in_reach)
    interact(game)
    scene = advance_dialogue(game)
    assert game.scene is world
    return scene.dialogue.id


def solve(
    game: Game,
    world: WorldScene,
    altar_name: str,
    language: str = "python",
    expect_phase: int | None = None,
) -> AltarScene:
    """Open the altar via INTERACT, clear the buffer (ggdG), type the reference solution
    through the KeyTranslator path, cast with ``:w`` and let the scene close."""
    altar = by_name(world.altars, altar_name)
    world.player.place_center(*altar.center)
    assert world.altar_in_reach() is altar
    interact(game)
    scene = game.scene
    assert isinstance(scene, AltarScene), f"altar {altar_name} did not open: {world.message!r}"
    assert scene.phase == expect_phase
    if scene.language != language:
        command(game, f"lang {language}")
        assert scene.language == language, scene.editor.last_message
    solution = scene.body.languages[language].solution.rstrip("\n")
    type_text(game, "ggdG")
    type_text(game, "i" + solution)
    press(game, pygame.K_ESCAPE)
    assert scene.editor.mode is EditorMode.NORMAL
    assert scene.editor.text == solution
    command(game, "w")
    res = scene.result
    assert res is not None, scene.notice
    assert res.passed, (res.message, res.first_failure)
    assert scene.closing is not None
    steps(game, CLOSE_DELAY_S + 0.1)
    assert game.scene is world
    return scene


def cross_door(game: Game, world: WorldScene, door_name: str) -> None:
    """Step on the door and run frames until the transition lands; check the spawn."""
    door = by_name(world.doors, door_name)
    assert not door.locked, f"{door_name} is locked: {door.lock_reason}"
    before = world.map_key
    target, spawn = door.target, door.spawn
    game.step()  # arm doors: the hero is not on an exit
    world.player.place_center(*door.center)
    for _ in range(round((2 * FADE_TIME + 0.5) / DT)):
        game.step()
        if world.map_key == target and not world.fade.active:
            break
    assert world.map_key == target, f"{door_name}: still in {world.map_key} (from {before})"
    assert not world.fade.active
    point = by_name(world.tilemap.data.objects_of_type("player_spawn"), spawn)
    assert world.player.center == pytest.approx(point.center)
    assert world.player.box is not None and not any(
        d.is_exit and _overlaps(world.player.box, d.box) for d in world.doors
    ), "spawned on top of a door"


def _overlaps(a, b) -> bool:
    return a[0] < b[0] + b[2] and b[0] < a[0] + a[2] and a[1] < b[1] + b[3] and b[1] < a[1] + a[3]


def face(game: Game, world: WorldScene, key: str) -> None:
    """Tap a movement key for one frame so the hero faces that way."""
    code = pygame.key.key_code(key)
    send(game, keydown(code, key))
    game.step()
    send(game, keyup(code))


# (offset of the hero from the target, in px; key that faces the target)
APPROACHES = (((0, -14), "j"), ((0, 14), "k"), ((-14, 0), "l"), ((14, 0), "h"))


def strike(game: Game, world: WorldScene, enemy, tries: int = 30) -> bool:
    """Approach ``enemy`` from a free side, face it and press ``x`` until it dies."""
    for _ in range(tries):
        if not enemy.alive:
            return True
        while world.player.attacking:
            game.step()
        ex, ey = enemy.center
        (ox, oy), key = next(
            (off, k) for off, k in APPROACHES
            if not world.collision.is_solid(int((ex + off[0]) // TILE), int((ey + off[1]) // TILE))
        )
        px, py = ex + ox, ey + oy
        world.player.place_center(px, py)
        face(game, world, key)
        world.player.place_center(px, py)
        press(game, pygame.K_x, "x")
        steps(game, 0.2)
    return not enemy.alive


def crown_strike(game: Game, world: WorldScene, boss: Grubble) -> None:
    """Knock off the three crown letters with real ``x`` strikes from above."""
    for _ in range(40):
        if boss.stunned:
            return
        while world.player.attacking or boss.letter_cooldown > 0:
            game.step()
        letter = next(c for c in boss.letters if not c.struck)
        lx, ly = letter.center
        world.player.place_center(lx, ly - 16)
        face(game, world, "j")
        lx, ly = letter.center
        world.player.place_center(lx, ly - 16)
        press(game, pygame.K_x, "x")
        game.step()
    raise AssertionError("could not stun Grubble")


def flags(game: Game) -> set[str]:
    return game.progress.flags


# ---- Prologue: the scriptorium ------------------------------------------------------------
def test_new_game_starts_in_scriptorium(s):
    game, world = s.game, s.world
    assert game.world is world and game.scene is world
    assert world.map_key == "little_tilde_scriptorium"
    assert "entered:little_tilde" in flags(game)
    spawn = by_name(world.tilemap.data.objects_of_type("player_spawn"), "spawn")
    assert world.player.center == pytest.approx(spawn.center)
    # Pell speaks on wakeup: the scriptorium's intro_dialogue plays before the player moves.
    game.step(1 / 60)
    intro = advance_dialogue(game)
    assert intro.dialogue.id == "pell_intro" and "met:pell" in flags(game)
    dx, dy = walk(game, world, "l", 0.25)
    assert dx > 15 and dy == pytest.approx(0)
    dx, dy = walk(game, world, "j", 0.2)
    assert dy > 10 and dx == pytest.approx(0)


def test_pell_sends_wren_for_ink(s):
    game, world = s.game, s.world
    assert talk(game, world, "Pell") == "pell_ink_reminder"
    assert talk(game, world, "ink_shelf") == "ink_shelf"
    assert "got_ink" in flags(game)
    assert talk(game, world, "Pell") == "pell_strike"
    assert "learned_x" in flags(game)


def test_scriptorium_door_to_village(s):
    cross_door(s.game, s.world, "to_village")
    assert s.world.map_key == "little_tilde"


# ---- Prologue: Little Tilde ---------------------------------------------------------------
def test_village_walk_and_moth(s):
    game, world = s.game, s.world
    dx, _ = walk(game, world, "l", 0.25)
    assert dx > 15
    assert talk(game, world, "Moth") == "moth_intro"
    assert "moth_joined" in flags(game)


def test_strike_out_the_typo_mites(s):
    game, world = s.game, s.world
    xp0 = game.progress.xp
    mites = [e for e in world.enemies if e.kind == "typo_mite"]
    assert sorted(m.name for m in mites) == ["mite_a", "mite_b", "mite_c"]
    for mite in mites:
        assert strike(game, world, mite), f"{mite.name} survived"
    game.step()
    assert not [e for e in world.enemies if e.kind == "typo_mite"]
    assert game.progress.xp == xp0 + 3 * 5
    assert world.player.hp > 0


def test_prologue_altars(s):
    game, world = s.game, s.world
    gate = by_name(world.doors, "north_gate")
    assert gate.locked
    solve(game, world, "village_lantern")
    assert game.progress.is_solved("ch0-01", "python")
    solve(game, world, "gate_chant")
    assert gate.locked
    solve(game, world, "pell_ward")
    for pid in ("ch0-01", "ch0-02", "ch0-03"):
        assert f"solved:{pid}" in flags(game)
        assert game.progress.is_solved(pid)
    game.step()
    assert not gate.locked


@pytest.mark.skipif("bash" not in available(), reason="bash not installed")
def test_lantern_in_bash_is_bilingual(s):
    game, world = s.game, s.world
    solve(game, world, "village_lantern", language="bash")
    assert game.progress.is_solved("ch0-01", "bash")
    assert game.progress.is_bilingual("ch0-01")
    assert "bilingual:ch0-01" in flags(game)


def test_cole_and_the_first_seal(s):
    game, world = s.game, s.world
    assert talk(game, world, "Cole") == "cole_intro"
    assert {"ledger_unlocked", "help_unlocked", "quest_rootholm"} <= flags(game)
    stone = by_name(world.waystones, "tilde")
    _stand_near(world, stone, world.waystone_in_reach)
    interact(game)
    menu = game.scene
    assert isinstance(menu, WaystoneMenu) and menu.choice == "seal"
    press(game, pygame.K_RETURN, "\r")
    assert game.scene is world
    assert world.last_waystone == ("little_tilde", "tilde")
    ledger = game.saves.ledger("slot1")
    if ledger.available:
        m = re.search(r"git commit -> ([0-9a-f]{4,})", world.message)
        assert m, world.message
        assert m.group(1) in [e.sha for e in ledger.log(5)]
    else:
        assert world.message == "Saved."
    assert "first_seal" in flags(game)


def test_north_gate_to_echo_vale(s):
    game, world = s.game, s.world
    flags(game).discard("entered:echo_vale")
    cross_door(game, world, "north_gate")
    assert world.map_key == "echo_vale"
    assert "entered:echo_vale" in flags(game)


# ---- Chapter 1: Echo Vale -----------------------------------------------------------------
def test_vale_walk_pip_namestone_and_toll(s):
    game, world = s.game, s.world
    _, dy = walk(game, world, "k", 0.25)
    assert dy < -15
    assert world.unlocked.isdisjoint({"dash", "counts", "visual", "cleave", "rewind"})
    assert talk(game, world, "pip") == "pip_intro"
    assert {"met_pip", "learned_w", "learned_b", "learned_e"} <= flags(game)
    assert "dash" in world.unlocked  # Pip teaches the Runner's Stride
    assert world.toast == "New stance learned: w / b / e  dash"
    solve(game, world, "namestone")
    toll = by_name(world.doors, "toll_gate")
    assert toll.locked
    solve(game, world, "toll_bridge")
    game.step()
    assert not toll.locked
    assert {"ch0-01", "ch0-02", "ch0-03", "ch1-01", "ch1-03"} <= set(game.progress.solved)


def test_save_and_restore_midway(s):
    game, world = s.game, s.world
    teleport(world, 12, 13)
    game.step()
    command(game, "save")
    assert game.scene is world
    assert world.message.startswith(("Sealed in the Ledger", "Saved."))
    other = Game(headless=True)
    restored = start_world(other, START_MAP, new=False)
    assert restored.map_key == "echo_vale"
    assert set(other.progress.solved) == set(game.progress.solved)
    assert other.progress.solved == game.progress.solved
    assert restored.player.center == pytest.approx(world.player.center)
    assert "entered:echo_vale" in other.progress.flags
    assert restored.player.coins == world.player.coins
    assert restored.unlocked == world.unlocked and restored.toast is None


def test_toll_gate_orchard_and_ferry(s):
    game, world = s.game, s.world
    cross_door(game, world, "toll_gate")  # same map: over the bridge
    assert world.map_key == "echo_vale"
    solve(game, world, "apples")
    ferry = by_name(world.doors, "ferry")
    assert ferry.locked
    solve(game, world, "ferry")
    game.step()
    assert not ferry.locked


def test_back_over_the_bridge_for_the_crier(s):
    game, world = s.game, s.world
    cross_door(game, world, "bridge_back")
    solve(game, world, "town_crier")
    assert game.progress.is_solved("ch1-06")
    cross_door(game, world, "toll_gate")


def test_ferry_to_crossroads(s):
    cross_door(s.game, s.world, "ferry")
    assert s.world.map_key == "crossroads"


# ---- Chapter 1: the Crossroads ------------------------------------------------------------
def test_crossroads_tally_receipt_and_chest(s):
    game, world = s.game, s.world
    dx, _ = walk(game, world, "l", 0.25)
    assert dx > 15
    assert talk(game, world, "Tally") == "tally_intro"
    assert "met_tally" in flags(game)
    hall = by_name(world.doors, "hall_gate")
    assert hall.locked
    solve(game, world, "receipt")
    assert talk(game, world, "Tally") == "tally_shop"
    assert "shop_open" in flags(game)
    coins = world.player.coins
    chest = by_name(world.chests, "inn_chest")
    _stand_near(world, chest, world.chest_in_reach)
    interact(game)
    assert chest.opened and world.player.coins == coins + 15
    interact(game)
    assert world.player.coins == coins + 15
    game.step()
    assert not hall.locked


def test_into_the_hall_of_echoes(s):
    cross_door(s.game, s.world, "hall_gate")
    assert s.world.map_key == "hall_of_echoes"


def test_grubble_declares_himself_on_entry(s):
    """The map's ``intro_dialogue: grubble`` plays on entry, before the fight."""
    game, world = s.game, s.world
    game.step()
    scene = game.scene
    assert isinstance(scene, DialogueScene) and scene.dialogue.id == "grubble_intro"
    advance_dialogue(game)
    assert game.scene is world
    assert {"grubble_declared", "seen:grubble_intro"} <= flags(game)
    game.step()
    assert game.scene is world  # plays once


# ---- Chapter 1 boss: Grubble ----------------------------------------------------------------
LECTERNS = ("lectern_a", "lectern_b", "lectern_c")


def test_grubble_three_lecterns(s):
    game, world = s.game, s.world
    dx, _ = walk(game, world, "l", 0.2)
    assert dx > 10
    bosses = [e for e in world.enemies if isinstance(e, Boss)]
    assert len(bosses) == 1 and isinstance(bosses[0], Grubble)
    boss = bosses[0]
    assert world.active_boss() is boss
    # A lectern refuses while he is wild.
    lectern = by_name(world.altars, "lectern_a")
    world.player.place_center(*lectern.center)
    interact(game)
    assert game.scene is world and "Stun it first" in world.message
    for phase, name in enumerate(LECTERNS):
        if phase:  # let the stun wear off so the crown regrows, then stun him again
            teleport(world, 1, 14)
            for _ in range(round(8 / DT)):
                if not boss.stunned:
                    break
                game.step()
            assert not boss.stunned and not any(c.struck for c in boss.letters)
        crown_strike(game, world, boss)
        assert boss.stunned and boss.open_lectern(phase)
        assert all(c.struck for c in boss.letters)
        solve(game, world, name, expect_phase=phase)
        assert phase in boss.solved
        assert f"phase:ch1-b:{phase}" in flags(game)
    assert boss.dying
    ledger = game.saves.ledger("slot1")
    if ledger.available:  # sealed before tagging: the tag points at the post-win commit
        assert "ch1" in ledger.tags()
        assert "ch1-b solved" in ledger.log(1)[0].message
        assert "Ledger as ch1" in world.message
    steps(game, 1.7)
    assert not boss.alive and boss not in world.enemies
    scene = game.scene  # the map's defeat_dialogue plays once he falls
    assert isinstance(scene, DialogueScene) and scene.dialogue.id == "grubble_defeated"
    advance_dialogue(game)
    assert game.scene is world
    assert "solved:ch1-b" in flags(game)
    assert game.progress.is_solved("ch1-b")
    ledger = game.saves.ledger("slot1")
    if ledger.available:
        assert "ch1" in ledger.tags()


def test_hall_exit_back_to_echo_vale(s):
    game, world = s.game, s.world
    cross_door(game, world, "exit")
    assert world.map_key == "echo_vale"
    assert talk(game, world, "Pell") == "pell_ch1_word"
    assert "pell_word1" in flags(game)
    assert talk(game, world, "pip") == "pip_after_boss"


# ---- standalone findings --------------------------------------------------------------------
def test_second_lectern_opens_with_its_own_starter(tmp_path, monkeypatch):
    monkeypatch.setenv("CODEROGUE_HOME", str(tmp_path))
    game = Game(headless=True)
    world = WorldScene(game, resource_path("content", "maps", "hall_of_echoes.tmj"))
    game.push(world)
    game.step()
    advance_dialogue(game)  # Grubble's declaration
    boss = world.active_boss()
    assert isinstance(boss, Grubble)
    crown_strike(game, world, boss)
    solve(game, world, "lectern_a", expect_phase=0)
    teleport(world, 1, 14)
    while boss.stunned:
        game.step()
    crown_strike(game, world, boss)
    lectern = by_name(world.altars, "lectern_b")
    world.player.place_center(*lectern.center)
    interact(game)
    scene = game.scene
    assert isinstance(scene, AltarScene) and scene.phase == 1
    starter = scene.spec.body_for(1).languages[scene.language].starter.rstrip("\n")
    assert scene.editor.text == starter
    # Phase a's code is kept under its own key; re-opening lectern a is refused.
    assert game.progress.draft("ch1-b#0", scene.language) is not None
    assert game.progress.draft("ch1-b", scene.language) is None
    command(game, "q")
    assert game.scene is world
    lectern_a = by_name(world.altars, "lectern_a")
    world.player.place_center(*lectern_a.center)
    interact(game)
    assert game.scene is world
    assert world.message == "This lectern's phase is already won."
