"""Scripted headless playthrough of Chapter 2: Branchwood, the Looping Mire, the Ouroboros.

Same conventions as ``test_playthrough_ch1``: the tests run in file order and share one Game
(module fixture). The save starts with every Prologue and Chapter 1 puzzle solved (progress
seeded directly), on the Crossroads. Long walks are ``teleport``s; everything else goes
through the real event path: INTERACT, dialogue keys, altar editors (``:w`` casts), the
waystone menu, ``x`` strikes, ``v`` lock-on, counts, ``dd``, ``u`` and door transitions.
"""

from __future__ import annotations

import math
from pathlib import Path

import pygame
import pytest

from coderogue.altar import AltarScene, game_puzzles
from coderogue.altar.scene import CLOSE_DELAY_S
from coderogue.app import Game, resource_path, start_world
from coderogue.editor.vim import Mode as EditorMode
from coderogue.entities.boss import OURO_GLOW_INTERVAL, Ouroboros
from coderogue.entities.player import REWIND_TIME
from coderogue.entities.waystone import WaystoneMenu
from coderogue.input.modes import Mode
from coderogue.story.scene import DialogueScene
from coderogue.world.scene import WorldScene
from coderogue.world.transitions import FADE_TIME

DT = 1 / 60
TILE = 16
START_MAP = resource_path("content", "maps", "crossroads.tmj")
PRIOR_CHAPTERS = (0, 1)
ENTERED = ("entered:little_tilde", "entered:echo_vale")


# ---- shared session -----------------------------------------------------------------------
class Session:
    game: Game
    world: WorldScene
    home: Path


def seed_progress(game: Game, chapters: tuple[int, ...], entered: tuple[str, ...]) -> None:
    """Mark every puzzle of ``chapters`` solved (in python) and set the ``entered:`` flags,
    as a save made at the end of those chapters would have them."""
    progress = game.progress
    for pid, spec in game_puzzles(game).items():
        if spec.chapter in chapters:
            progress.mark_solved(pid, "python", xp=spec.reward.xp)
            progress.flags.add(f"solved:{pid}")
    progress.flags.update(entered)


@pytest.fixture(scope="module")
def s(tmp_path_factory):
    home = tmp_path_factory.mktemp("coderogue_home")
    with pytest.MonkeyPatch.context() as mp:
        mp.setenv("CODEROGUE_HOME", str(home))
        game = Game(headless=True)
        world = start_world(game, START_MAP, new=True)
        seed_progress(game, PRIOR_CHAPTERS, ENTERED)
        world.load_map(world.map_path)  # rebuild doors/altars against the seeded save
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


def tap(game: Game, ch: str) -> None:
    """One printable key as SDL sends it (KEYDOWN with unicode, then KEYUP)."""
    code = pygame.key.key_code(ch)
    send(game, keydown(code, ch), keyup(code))


def type_text(game: Game, text: str) -> None:
    """Each character as SDL sends it: a KEYDOWN (with unicode) then its TEXTINPUT.
    ``\\n`` is the Enter key."""
    for ch in text:
        if ch == "\n":
            press(game, pygame.K_RETURN)
            continue
        code = ord(ch.lower()) if ch.isascii() else 0
        send(game, keydown(code, ch), pygame.event.Event(pygame.TEXTINPUT, text=ch))


def type_code(game: Game, code: str) -> None:
    """Type ``code`` in INSERT mode like a player: the editor keeps the previous line's
    indent on Enter, so only the extra indent is typed, or Backspace dedents."""
    indent = 0
    for i, line in enumerate(code.split("\n")):
        body = line.lstrip(" ")
        want = len(line) - len(body)
        if i:
            press(game, pygame.K_RETURN)
            for _ in range(max(0, indent - want)):
                press(game, pygame.K_BACKSPACE, "\b")
            line = " " * max(0, want - indent) + body
        type_text(game, line)
        indent = want if body else 0


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
    type_text(game, "i")
    type_code(game, solution)
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


def face(game: Game, world: WorldScene, key: str) -> None:
    """Tap a movement key for one frame so the hero faces that way (NORMAL mode)."""
    assert world.modes.mode is Mode.NORMAL
    code = pygame.key.key_code(key)
    send(game, keydown(code, key))
    game.step()
    send(game, keyup(code))


# (offset of the hero from the target, in px; key that faces the target)
APPROACHES = (((0, -14), "j"), ((0, 14), "k"), ((-14, 0), "l"), ((14, 0), "h"))


def _approach(game: Game, world: WorldScene, enemy) -> None:
    """Stand next to ``enemy`` on a free side, facing it."""
    while world.player.attacking:
        game.step()
    ex, ey = enemy.center
    (ox, oy), key = next(
        (off, k) for off, k in APPROACHES
        if not world.collision.is_solid(int((ex + off[0]) // TILE), int((ey + off[1]) // TILE))
    )
    world.player.place_center(ex + ox, ey + oy)
    face(game, world, key)
    world.player.place_center(ex + ox, ey + oy)


def strike(game: Game, world: WorldScene, enemy, tries: int = 30) -> bool:
    """Approach ``enemy`` from a free side, face it and press ``x`` until it dies."""
    for _ in range(tries):
        if not enemy.alive:
            return True
        _approach(game, world, enemy)
        press(game, pygame.K_x, "x")
        steps(game, 0.2)
    return not enemy.alive


def locked_strike(game: Game, world: WorldScene, enemy, tries: int = 20) -> bool:
    """Face ``enemy``, lock on with ``v`` (VISUAL), strike with ``x``, release with ``v``."""
    for _ in range(tries):
        if not enemy.alive:
            break
        if world.modes.mode is Mode.VISUAL:
            tap(game, "v")
        _approach(game, world, enemy)
        tap(game, "v")
        assert world.modes.mode is Mode.VISUAL and world.locked_target is enemy
        press(game, pygame.K_x, "x")
        steps(game, 0.2)
    if world.modes.mode is Mode.VISUAL:
        tap(game, "v")
    return not enemy.alive


def flags(game: Game) -> set[str]:
    return game.progress.flags


def seal_at(game: Game, world: WorldScene, stone_name: str) -> None:
    stone = by_name(world.waystones, stone_name)
    _stand_near(world, stone, world.waystone_in_reach)
    interact(game)
    menu = game.scene
    assert isinstance(menu, WaystoneMenu) and menu.choice == "seal"
    press(game, pygame.K_RETURN, "\r")
    assert game.scene is world
    assert world.last_waystone == (world.map_key, stone_name)


# ---- the Crossroads: the north gate ------------------------------------------------------
def test_seeded_save_opens_the_north_gate(s):
    game, world = s.game, s.world
    assert world.map_key == "crossroads"
    assert {"ch0-01", "ch1-07", "ch1-b"} <= set(game.progress.solved)
    gate = by_name(world.doors, "north_gate")
    assert not gate.locked, gate.lock_reason
    cross_door(game, world, "north_gate")
    assert world.map_key == "branchwood"
    assert "entered:branchwood" in flags(game)


# ---- Branchwood ----------------------------------------------------------------------------
def test_branchwood_walk_and_weighbridge(s):
    game, world = s.game, s.world
    _, dy = walk(game, world, "k", 0.25)
    assert dy < -15
    bridge = by_name(world.doors, "weighbridge")
    assert bridge.locked
    solve(game, world, "weighbridge")
    assert game.progress.is_solved("ch2-01")
    game.step()
    assert not bridge.locked
    cross_door(game, world, "weighbridge")  # same map: over the gorge


def test_sable_gives_the_spyglass(s):
    game, world = s.game, s.world
    assert talk(game, world, "sable") == "sable_first"
    assert {"met_sable", "got_spyglass", "learned_v"} <= flags(game)
    assert talk(game, world, "sable") == "sable_repeat"
    assert "visual" in world.unlocked


def test_null_wisps_only_take_locked_hits(s):
    game, world = s.game, s.world
    wisps = [e for e in world.enemies if e.kind == "null_wisp"]
    assert sorted(w.name for w in wisps) == ["wisp_a", "wisp_b", "wisp_c"]
    wisp = by_name(wisps, "wisp_a")
    # Unlocked, x passes straight through it.
    assert not strike(game, world, wisp, tries=3)
    assert wisp.alive and wisp.hp == wisp.max_hp
    assert world.locked_target is None
    xp0 = game.progress.xp
    for w in sorted(wisps, key=lambda e: e.name):
        world.player.hp = world.player.max_hp
        assert locked_strike(game, world, w), f"{w.name} survived the locked strikes"
    game.step()
    assert not [e for e in world.enemies if e.kind == "null_wisp"]
    assert game.progress.xp == xp0 + 3 * 5
    assert world.modes.mode is Mode.NORMAL and world.locked_target is None


def test_crow_letter_and_count_dash(s):
    game, world = s.game, s.world
    assert talk(game, world, "crow_letter") == "crow_letter"
    assert {"read_crow_letter", "learned_counts"} <= flags(game)
    # 3j: dash three tiles down (the column below must be open floor)
    tx, ty = 31, 5
    assert not any(world.collision.is_solid(tx, ty + k) for k in range(4))
    teleport(world, tx, ty)
    game.step()
    x0, y0 = world.player.center
    tap(game, "3")
    tap(game, "j")
    steps(game, 0.4)
    x1, y1 = world.player.center
    assert y1 - y0 == pytest.approx(3 * TILE, abs=0.5) and x1 == pytest.approx(x0)
    assert world.player.facing == (0, 1)


def test_cleave_a_looper_row_double_damage(s):
    game, world = s.game, s.world
    loopers = [by_name(world.enemies, n) for n in ("looper_a", "looper_b")]
    assert all(lp.kind == "looper" and lp.hp == 4 for lp in loopers)
    # stand in their row between them and cleave both sides of it at once
    ys = {round(lp.center[1]) for lp in loopers}
    assert len(ys) == 1
    world.player.hp = world.player.max_hp
    cx = (loopers[0].center[0] + loopers[1].center[0]) / 2
    world.player.place_center(cx, loopers[0].center[1])
    face(game, world, "l")
    world.player.place_center(cx, loopers[0].center[1])
    tap(game, "d")
    tap(game, "d")
    assert [lp.hp for lp in loopers] == [2, 2]  # CLEAVE_DAMAGE 1 x2 against loopers
    steps(game, 0.7)  # cooldown and enemy i-frames
    for lp in loopers:
        if lp.alive:
            assert strike(game, world, lp)
    # one plain x strike does 1 against a looper
    other = by_name(world.enemies, "looper_c")
    _approach(game, world, other)
    press(game, pygame.K_x, "x")
    steps(game, 0.2)
    assert other.hp == 3


def test_door_to_the_mire(s):
    game, world = s.game, s.world
    world.player.hp = world.player.max_hp
    cross_door(game, world, "to_mire")
    assert world.map_key == "looping_mire"
    assert "entered:looping_mire" in flags(game)


# ---- the Looping Mire ---------------------------------------------------------------------
def test_mire_bells(s):
    game, world = s.game, s.world
    dx, _ = walk(game, world, "l", 0.25)
    assert dx > 15
    solve(game, world, "bells")
    assert game.progress.is_solved("ch2-03")


def test_ono_and_the_hourglass_rewind(s):
    game, world = s.game, s.world
    assert talk(game, world, "ono") == "ono_first"
    assert {"got_hourglass", "learned_u"} <= flags(game)
    teleport(world, 28, 11)
    game.step()
    start = world.player.center
    charges = world.player.u_charges
    dx, _ = walk(game, world, "h", 1.0)
    assert dx < -50
    tap(game, "u")
    assert world.player.rewinding
    assert world.player.u_charges == charges - 1
    steps(game, REWIND_TIME + 0.1)
    assert not world.player.rewinding
    assert world.player.center == pytest.approx(start, abs=1.5)


def test_cole_ledger_disaster_and_restore(s):
    game, world = s.game, s.world
    assert talk(game, world, "cole_mire") == "cole_mire_disaster"
    assert "ledger_disaster" in flags(game)
    assert "ledger_restored" not in flags(game)
    assert talk(game, world, "cole_mire") == "cole_mire_walkthrough"
    assert "ledger_restored" in flags(game)
    assert talk(game, world, "cole_mire") == "cole_mire_after"
    # The real Ledger: seal, clobber a spell on disk, diff it, restore it.
    seal_at(game, world, "mire")
    ledger = game.saves.ledger("slot1")
    if not ledger.available:
        pytest.skip("git not available: the Ledger is off")
    spell = game.saves.spell_path("slot1", "ch2-03", "python")
    assert spell.is_file()
    sealed = spell.read_text(encoding="utf-8")
    assert sealed.rstrip("\n") == game.progress.draft("ch2-03", "python").rstrip("\n")
    rel = spell.relative_to(game.saves.slot_dir("slot1")).as_posix()
    spell.write_text("# the Null ate this spell\n", encoding="utf-8")
    diff = ledger.diff(rel)
    assert "-" + sealed.splitlines()[0] in diff and "+# the Null ate this spell" in diff
    assert ledger.restore(rel)
    assert spell.read_text(encoding="utf-8") == sealed
    assert ledger.diff(rel) == ""


def test_lanterns_herbalist_and_swarm(s):
    game, world = s.game, s.world
    heart = by_name(world.doors, "to_heart")
    assert heart.locked
    solve(game, world, "lanterns")
    solve(game, world, "herbalist")
    solve(game, world, "swarm")
    for pid in ("ch2-04", "ch2-05", "ch2-06"):
        assert game.progress.is_solved(pid) and f"solved:{pid}" in flags(game)
    game.step()
    assert not heart.locked
    seal_at(game, world, "mire")
    assert world.last_waystone == ("looping_mire", "mire")


def test_into_the_mire_heart(s):
    game, world = s.game, s.world
    world.player.hp = world.player.max_hp
    cross_door(game, world, "to_heart")
    assert world.map_key == "mire_heart"
    game.step()
    scene = game.scene
    assert isinstance(scene, DialogueScene) and scene.dialogue.id == "ouroboros"
    advance_dialogue(game)
    assert game.scene is world
    game.step()
    assert game.scene is world  # plays once


# ---- Chapter 2 boss: the Ouroboros ---------------------------------------------------------
STONES = ("loop_stone_a", "loop_stone_b", "loop_stone_c")


def _wait_for_glow(game: Game, boss: Ouroboros):
    """Run frames (hero parked safely off the ring) until a segment glows."""
    for _ in range(round((OURO_GLOW_INTERVAL + 1) / DT)):
        glowing = [sg for sg in boss.segments if sg.glowing and not sg.severed]
        if glowing:
            return glowing[0]
        game.step()
    raise AssertionError("no segment started glowing")


def _cleave_glowing(game: Game, world: WorldScene, boss: Ouroboros, segment) -> None:
    """Line up with the glowing segment from inside the ring, lock on with v, cleave with dd."""
    cx, cy = boss.ring_center
    sx, sy = segment.center
    if abs(sy - cy) >= abs(sx - cx):  # near the top/bottom: cut the column
        spot, key = (sx, cy), ("k" if sy < cy else "j")
    else:  # near the left/right: cut the row
        spot, key = (cx, sy), ("h" if sx < cx else "l")
    world.player.hp = world.player.max_hp
    world.player.place_center(*spot)
    face(game, world, key)
    sx, sy = segment.center  # it moved during that frame
    spot = (sx, cy) if key in "jk" else (cx, sy)
    world.player.place_center(*spot)
    tap(game, "v")
    assert world.modes.mode is Mode.VISUAL and world.locked_target is segment
    tap(game, "d")
    tap(game, "d")
    tap(game, "v")
    assert world.modes.mode is Mode.NORMAL


def test_ouroboros_three_loop_stones(s):
    game, world = s.game, s.world
    boss = world.active_boss()
    assert isinstance(boss, Ouroboros)
    # A loop-stone refuses while the worm circles unhurt.
    stone = by_name(world.altars, "loop_stone_a")
    world.player.place_center(*stone.center)
    interact(game)
    assert game.scene is world and "Stun it first" in world.message
    for phase, name in enumerate(STONES):
        for _attempt in range(4):
            teleport(world, 11, 14)  # park by the south door, off the ring
            segment = _wait_for_glow(game, boss)
            _cleave_glowing(game, world, boss, segment)
            if boss.open_lectern(phase):
                break
        assert segment.severed and boss.open_lectern(phase), f"stone {name} did not open"
        assert not any(boss.open_lectern(i) for i in range(3) if i != phase)
        solve(game, world, name, expect_phase=phase)
        assert phase in boss.solved
        assert f"phase:ch2-b:{phase}" in flags(game)
        assert not boss.open_lectern(phase)
    assert boss.dying
    ledger = game.saves.ledger("slot1")
    if ledger.available:  # sealed before tagging: the tag points at the post-win commit
        assert "ch2" in ledger.tags()
        assert "ch2-b solved" in ledger.log(1)[0].message
        assert "Ledger as ch2" in world.message
    steps(game, 1.7)
    assert not boss.alive and boss not in world.enemies
    scene = game.scene
    assert isinstance(scene, DialogueScene) and scene.dialogue.id == "ouroboros_defeated"
    advance_dialogue(game)
    assert game.scene is world
    assert "solved:ch2-b" in flags(game)
    assert game.progress.is_solved("ch2-b")


def test_pell_second_words_and_the_road_north(s):
    game, world = s.game, s.world
    assert talk(game, world, "pell_ch2") == "pell_ch2_word"
    assert "pell_word2" in flags(game)
    assert talk(game, world, "pell_ch2") == "pell_ch2_after"
    north = by_name(world.doors, "to_directory")
    game.step()
    assert not north.locked, north.lock_reason
    cross_door(game, world, "to_directory")
    assert world.map_key == "grand_directory"
    assert "entered:grand_directory" in flags(game)


# ---- design gaps ----------------------------------------------------------------------------
def test_v_locks_on_to_the_glowing_segment(tmp_path, monkeypatch):
    monkeypatch.setenv("CODEROGUE_HOME", str(tmp_path))
    game = Game(headless=True)
    world = WorldScene(game, resource_path("content", "maps", "mire_heart.tmj"))
    game.push(world)
    game.step()
    advance_dialogue(game)
    boss = world.active_boss()
    assert isinstance(boss, Ouroboros)
    segment = _wait_for_glow(game, boss)
    sx, sy = segment.center
    cx, cy = boss.ring_center
    d = math.hypot(sx - cx, sy - cy)
    # stand just inside the ring, next to the glowing segment
    world.player.place_center(cx + (sx - cx) * (d - 18) / d, cy + (sy - cy) * (d - 18) / d)
    tap(game, "v")
    assert world.locked_target is segment
