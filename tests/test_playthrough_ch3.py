"""Scripted headless playthrough of Chapter 3: the Grand Directory, the Stacks, the Hollow
Archivist and the Top Gate (the end of the MVP).

Same conventions as ``test_playthrough_ch1``: the tests run in file order and share one Game
(module fixture). The save starts with every Prologue, Chapter 1 and Chapter 2 puzzle solved
(progress seeded directly), in the Grand Directory. Long walks are ``teleport``s; everything
else goes through the real event path: INTERACT, dialogue keys, altar editors (``:w``
casts), the waystone menu, ``x`` strikes, ``yy``/``p``, ``/`` + ``n``, marks and doors.
"""

from __future__ import annotations

from pathlib import Path

import pygame
import pytest

from coderogue.altar import AltarScene, game_puzzles
from coderogue.altar.scene import CLOSE_DELAY_S
from coderogue.app import Game, resource_path, start_world
from coderogue.editor.vim import Mode as EditorMode
from coderogue.entities.boss import ARCHIVIST_STUN, HollowArchivist
from coderogue.entities.enemies import StampGolem
from coderogue.entities.waystone import WaystoneMenu
from coderogue.input.modes import Mode
from coderogue.languages import available, get
from coderogue.languages.base import LanguageRuntime
from coderogue.puzzles import run_puzzle, run_script
from coderogue.puzzles.runner import resolve_runtime
from coderogue.story.scene import DialogueScene
from coderogue.world.scene import WorldScene
from coderogue.world.transitions import FADE_TIME, NULL_DOOR_MESSAGE

DT = 1 / 60
TILE = 16
START_MAP = resource_path("content", "maps", "grand_directory.tmj")
PRIOR_CHAPTERS = (0, 1, 2)
ENTERED = (
    "entered:little_tilde", "entered:echo_vale", "entered:branchwood", "entered:looping_mire",
)


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


def wait_for_fade(game: Game, world: WorldScene) -> None:
    game.step()
    for _ in range(round((2 * FADE_TIME + 0.5) / DT)):
        if not world.fade.active:
            return
        game.step()
    raise AssertionError("the fade never finished")


def yank_from(game: Game, world: WorldScene, crate_name: str, below: tuple[int, int]) -> None:
    """Stand on ``below`` facing up at the crate and press ``yy``."""
    crate = by_name(world.liftables, crate_name)
    teleport(world, *below)
    face(game, world, "k")
    teleport(world, *below)
    assert world.liftable_in_reach() is crate
    tap(game, "y")
    tap(game, "y")
    assert world.player.carrying is crate and crate not in world.liftables


def put_on(game: Game, world: WorldScene, plate_name: str, key: str) -> None:
    """Stand next to the plate (on the side opposite ``key``), face it and press ``p``."""
    plate = by_name(world.plates, plate_name)
    px, py = int(plate.center[0] // TILE), int(plate.center[1] // TILE)
    dx, dy = {"h": (1, 0), "l": (-1, 0), "k": (0, 1), "j": (0, -1)}[key]
    teleport(world, px + dx, py + dy)
    face(game, world, key)
    teleport(world, px + dx, py + dy)
    assert world.front_tile() == (px, py)
    crate = world.player.carrying
    assert crate is not None
    tap(game, "p")
    assert world.player.carrying is None and crate in world.liftables
    game.step()
    assert plate.pressed


def search_for(game: Game, world: WorldScene, term: str) -> None:
    """``/term<CR>`` through the world's search prompt."""
    send(game, keydown(pygame.K_SLASH, "/"))
    assert world.search_input == ""
    for ch in term:
        send(game, keydown(pygame.key.key_code(ch), ch))
    assert world.search_input == term
    press(game, pygame.K_RETURN, "\r")
    assert world.search_input is None


# ---- the Grand Directory -------------------------------------------------------------------
def test_dex_panics_and_the_inventory(s):
    game, world = s.game, s.world
    assert world.map_key == "grand_directory"
    assert {"ch0-01", "ch1-b", "ch2-b"} <= set(game.progress.solved)
    assert "entered:grand_directory" in flags(game)
    _, dy = walk(game, world, "k", 0.25)
    assert dy < -15
    assert talk(game, world, "Dex") == "dex_panic"
    assert "met_dex" in flags(game)
    assert talk(game, world, "Dex") == "dex_waiting"
    solve(game, world, "inventory")
    assert game.progress.is_solved("ch3-01", "python")


@pytest.mark.skipif("bash" not in available(), reason="bash not installed")
def test_inventory_bash_variant_is_usable(s):
    """3-01 needs bash >= 4 (associative arrays); this machine's bash qualifies, so the
    variant is offered, not greyed out, and its reference solution casts."""
    game, world = s.game, s.world
    spec = game_puzzles(game)["ch3-01"]
    assert spec.requires.get("bash") == ">=4"
    bash = get("bash")
    runtime = resolve_runtime(spec, bash)  # raises RunnerError if bash is too old
    assert bash.version_satisfies(runtime, ">=4")
    scene = solve(game, world, "inventory", language="bash")
    assert "bash" in scene.usable
    assert game.progress.is_bilingual("ch3-01")


def test_dex_teaches_yank_and_the_gallery_plate(s):
    game, world = s.game, s.world
    assert talk(game, world, "Dex") == "dex_first"
    assert "learned_yank" in flags(game)
    gate = by_name(world.doors, "/directory/gossip-gallery")
    assert gate.locked
    yank_from(game, world, "crate_tutorial", (4, 20))
    dx, _ = walk(game, world, "l", 0.3)  # carry it a few steps
    assert dx > 15 and world.player.carrying is not None
    put_on(game, world, "plate_gallery", "k")
    assert not gate.locked
    assert world.crates["grand_directory"]["crate_tutorial"] == [9, 11]


def test_gossip_gallery(s):
    game, world = s.game, s.world
    shortcut = by_name(world.doors, "/directory/front-hall")
    assert shortcut.locked
    solve(game, world, "gossip")
    assert game.progress.is_solved("ch3-02")
    game.step()
    assert not shortcut.locked


def test_greeting_rite_dismisses_the_golems(s):
    game, world = s.game, s.world
    assert talk(game, world, "stamp_golem") == "golem"
    golems = [e for e in world.enemies if isinstance(e, StampGolem)]
    assert sorted(g.name for g in golems) == ["golem_a", "golem_b"]
    game.step()
    assert all(g.blocked_tiles for g in golems)
    reading = by_name(world.doors, "/directory/reading-room")
    assert reading.locked
    xp0 = game.progress.xp
    solve(game, world, "greeting_rite")
    assert game.progress.is_solved("ch3-03")
    assert all(g.dismissed and not g.alive for g in golems)
    assert not [e for e in world.enemies if isinstance(e, StampGolem)]
    game.step()
    assert not reading.locked
    for g in golems:
        tx, ty = int(g.center[0] // TILE), int(g.center[1] // TILE)
        assert not world.collision.is_solid(tx, ty)
    spec = game_puzzles(game)["ch3-03"]
    assert game.progress.xp == xp0 + spec.reward.xp  # leaving is not a kill
    assert talk(game, world, "stamp_golem") == "golem_after"


def test_dex_search_cole_marks_and_the_seal(s):
    game, world = s.game, s.world
    assert talk(game, world, "Dex") == "dex_search"
    assert "learned_search" in flags(game)
    assert talk(game, world, "Cole") == "cole_dir_first"
    assert "learned_marks" in flags(game)
    seal_at(game, world, "directory")
    assert world.waystone_in_reach() is not None
    tap(game, "m")
    assert world.pending_key == "m"
    tap(game, "a")
    assert world.marks["a"] == ("grand_directory", "directory")


def test_up_to_the_stacks(s):
    game, world = s.game, s.world
    cross_door(game, world, "to_stacks")
    assert world.map_key == "stacks"


# ---- the Stacks ---------------------------------------------------------------------------
def test_stacks_walk_and_ledger_file(s):
    game, world = s.game, s.world
    world.player.hp = world.player.max_hp
    _, dy = walk(game, world, "k", 0.25)
    assert dy < -15
    solve(game, world, "ledger_file")
    assert game.progress.is_solved("ch3-05")


def test_annex_crate_round_the_corner(s):
    game, world = s.game, s.world
    world.player.hp = world.player.max_hp
    door = by_name(world.doors, "/stacks/annex/flooded")
    assert door.locked
    yank_from(game, world, "crate_annex", (19, 13))
    _, dy = walk(game, world, "k", 1.0)  # up the long arm of the L, crate overhead
    assert dy < -50
    put_on(game, world, "plate_annex", "l")  # ... and along the short arm to the plate
    assert not door.locked
    assert world.crates["stacks"]["crate_annex"] == [26, 6]


def test_search_finds_the_singed_scroll(s):
    game, world = s.game, s.world
    teleport(world, 24, 20)
    game.step()
    search_for(game, world, "scroll")
    names = [e.name for e in world.search_matches]
    assert names == ["singed_scroll"], names
    assert world.message.startswith("/scroll: 1 match")
    tap(game, "n")
    assert world.current_match is by_name(world.altars, "singed_scroll")
    assert world.focus is world.current_match and world.focus_time > 0
    search_for(game, world, "wisp")
    assert len(world.search_matches) == 3
    seen = []
    for _ in range(4):
        tap(game, "n")
        seen.append(world.current_match.name)
    assert seen[3] == seen[0] and len(set(seen[:3])) == 3  # n wraps around
    press(game, pygame.K_ESCAPE)
    assert not world.search_matches


def test_singed_scroll_and_aqueduct(s):
    game, world = s.game, s.world
    world.player.hp = world.player.max_hp
    solve(game, world, "singed_scroll")
    assert game.progress.is_solved("ch3-06")
    spec = game_puzzles(game)["ch3-06"]
    assert spec.body_for(None).fixtures, "3-06 reads a fixture file"
    census = by_name(world.doors, "/stacks/census")
    assert census.locked
    world.player.hp = world.player.max_hp
    solve(game, world, "aqueduct")
    assert game.progress.is_solved("ch3-07")
    game.step()
    assert not census.locked
    assert not by_name(world.doors, "/stacks/aqueduct").locked


def test_jump_to_mark_and_back(s):
    game, world = s.game, s.world
    wisp = by_name(world.enemies, "wisp_flood")
    world.player.hp = world.player.max_hp
    world.player.place_center(wisp.center[0] - 32, wisp.center[1])
    game.step()
    tap(game, "'")
    tap(game, "a")
    assert world.message == "Not while bugs are near." and world.map_key == "stacks"
    assert locked_strike(game, world, wisp)
    game.step()
    assert not world.in_combat()
    tap(game, "'")
    tap(game, "a")
    wait_for_fade(game, world)
    assert world.map_key == "grand_directory"
    stone = by_name(world.waystones, "directory")
    assert world.player.center == pytest.approx(stone.stand_point)
    cross_door(game, world, "to_stacks")
    teleport(world, 40, 2)
    cross_door(game, world, "/stacks/census")
    assert world.map_key == "census_hall"


# ---- Chapter 3 boss: the Hollow Archivist --------------------------------------------------
LECTERNS = ("lectern_a", "lectern_b", "lectern_c", "lectern_d")


def expose(game: Game, world: WorldScene, boss: HollowArchivist) -> None:
    """Three real ``x`` strikes (it teleports every 3 s, so re-approach each time)."""
    for _ in range(30):
        if boss.stunned:
            return
        world.player.hp = world.player.max_hp
        _approach(game, world, boss)
        press(game, pygame.K_x, "x")
        steps(game, 0.3)
    raise AssertionError(f"could not expose the Archivist (hits {boss.hits})")


def test_archivist_files_cards(s):
    game, world = s.game, s.world
    assert talk(game, world, "hollow_archivist") == "archivist"


def test_archivist_four_lecterns(s):
    game, world = s.game, s.world
    boss = world.active_boss()
    assert isinstance(boss, HollowArchivist)
    lectern = by_name(world.altars, "lectern_a")
    world.player.place_center(*lectern.center)
    interact(game)
    assert game.scene is world and "Stun it first" in world.message
    for phase, name in enumerate(LECTERNS):
        if phase:  # let the exposure end, then expose it again
            teleport(world, 12, 13)
            for _ in range(round((ARCHIVIST_STUN + 0.5) / DT)):
                if not boss.stunned:
                    break
                game.step()
            assert not boss.stunned and not boss.dying
        expose(game, world, boss)
        assert boss.stunned and boss.open_lectern(phase)
        solve(game, world, name, expect_phase=phase)
        assert phase in boss.solved
        assert f"phase:ch3-b:{phase}" in flags(game)
        if phase < 3:
            assert not boss.dying, f"the Archivist fell after phase {phase} of 4"
    assert boss.dying
    ledger = game.saves.ledger("slot1")
    if ledger.available:
        assert "ch3" in ledger.tags()
        assert "ch3-b solved" in ledger.log(1)[0].message
    steps(game, 1.7)
    assert not boss.alive and boss not in world.enemies
    scene = game.scene
    assert isinstance(scene, DialogueScene) and scene.dialogue.id == "archivist_defeated"
    advance_dialogue(game)
    assert game.scene is world
    assert "solved:ch3-b" in flags(game) and game.progress.is_solved("ch3-b")


def test_restored_txt_is_written(s):
    """Phase d's test checks ``restored.txt``; PuzzleResult does not carry files, so run the
    phase's reference solution through the sandbox directly and read the file back."""
    spec = game_puzzles(s.game)["ch3-b"]
    body = spec.body_for(3)
    assert any(f.path == "restored.txt" for t in body.tests for f in t.expect.files)
    code = body.languages["python"].solution
    assert run_puzzle(spec, "python", code, 3).passed
    py = get("python")
    test = body.tests[0]
    res = run_script(py, resolve_runtime(spec, py), code, test.stdin, body.fixtures)
    restored = res.files.get("restored.txt", "")
    assert restored.strip(), res.files
    names = restored.split()
    assert names == sorted(names) and "Pell" in names


def test_pell_wrote_back(s):
    game, world = s.game, s.world
    npc = by_name(world.npcs, "Pell")
    _stand_near(world, npc, world.npc_in_reach)
    interact(game)
    scene = game.scene
    assert isinstance(scene, DialogueScene) and scene.dialogue.id == "pell_ch3_restored"
    assert "You wrote me back." in scene.dialogue.lines
    advance_dialogue(game)
    assert {"pell_restored", "morrow_road_seen"} <= flags(game)
    ledger = game.saves.ledger("slot1")
    if ledger.available:
        assert "ch3" in ledger.tags()
    cross_door(game, world, "top_gate")
    assert world.map_key == "top_gate"


# ---- the Top Gate: the end of the MVP ------------------------------------------------------
def test_the_road_to_rootholm_is_commented_out(s):
    game, world = s.game, s.world
    road = by_name(world.doors, "road_to_rootholm")
    assert road.locked and road.lock_reason == NULL_DOOR_MESSAGE
    assert not by_name(world.doors, "/directory/top-gate").locked
    teleport(world, 10, 3)
    game.step()
    _, dy = walk(game, world, "k", 1.0)
    assert dy < 0
    assert world.map_key == "top_gate"
    assert world.player.box[1] >= road.box[1] + road.box[3] - 0.01  # it never let us through
    assert world.message == NULL_DOOR_MESSAGE
    assert talk(game, world, "Pell") == "pell_ch3_gate"
    seal_at(game, world, "top_gate")


# ---- design gaps ----------------------------------------------------------------------------
def test_old_bash_greys_out_the_inventory_variant(tmp_path, monkeypatch):
    monkeypatch.setenv("CODEROGUE_HOME", str(tmp_path))
    bash = get("bash")
    old = LanguageRuntime("bash", "/bin/bash", (3, 2, 57), "3.2.57")
    monkeypatch.setattr(bash, "detect", lambda: old)
    game = Game(headless=True)
    world = WorldScene(game, START_MAP)
    game.push(world)
    altar = by_name(world.altars, "inventory")
    world.player.place_center(*altar.center)
    interact(game)
    scene = game.scene
    assert isinstance(scene, AltarScene)
    assert "python" in scene.usable
    assert "bash" not in scene.usable
