"""The real-time world scene: map, player, enemies, altars, camera and VIM-key input."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING

import pygame

from coderogue.entities import sprites
from coderogue.entities.altar import Altar
from coderogue.entities.base import Entity, StaticProp
from coderogue.entities.enemies import Wanderer
from coderogue.entities.npc import Npc
from coderogue.entities.player import Player
from coderogue.input.keymap import MOVE_ACTIONS, Action, Keymap
from coderogue.input.modes import Mode, ModeMachine
from coderogue.save.store import PlayerState, SaveState
from coderogue.scene import Scene
from coderogue.story.dialogue import DialogueBank
from coderogue.story.scene import DialogueScene
from coderogue.ui.hud import draw_hud
from coderogue.ui.text import draw_text, render_text
from coderogue.world.camera import Camera
from coderogue.world.collision import boxes_overlap
from coderogue.world.loader import MapObject
from coderogue.world.tilemap import TileMap

if TYPE_CHECKING:
    from coderogue.app import Game
    from coderogue.puzzles import PuzzleResult, PuzzleSpec

VIEW_SIZE = (320, 180)  # world pixels shown; scaled 3x to the 960x540 logical surface
BG_COLOR = (20, 16, 24)

PROP_SPRITES = {"npc": sprites.KNIGHT, "chest": sprites.CHEST}
SAVE_SLOT = "slot1"


def _tile_prop(obj: MapObject, default: int | None) -> int | None:
    value = obj.properties.get("tile", obj.properties.get("sprite", default))
    return int(value) if value is not None else None


class WorldScene(Scene):
    """Top-down real-time play in NORMAL mode.

    Pressing INTERACT (``i`` / Enter) at an altar calls :meth:`on_altar`, which by default
    pushes an :class:`~coderogue.altar.AltarScene` for the altar's puzzle. Set
    ``altar_handler`` (or override :meth:`on_altar`) to replace that. When a puzzle is solved
    the altar scene calls :meth:`on_puzzle_solved` (and :meth:`on_puzzle_skipped` on a skip).
    """

    def __init__(self, game: Game, map_path: str | Path, keymap: Keymap | None = None) -> None:
        super().__init__(game)
        self.map_path = Path(map_path)
        self.tilemap = TileMap.load(self.map_path)
        self.collision = self.tilemap.collision
        arrows = bool(getattr(game, "arrows_fallback", False))
        self.keymap = keymap or Keymap.default(arrows_fallback=arrows)
        self.modes = ModeMachine()
        self.held: list[Action] = []  # held move actions, in press order
        self.view = pygame.Surface(VIEW_SIZE).convert() if pygame.display.get_surface() else (
            pygame.Surface(VIEW_SIZE)
        )
        self.camera = Camera(
            VIEW_SIZE[0], VIEW_SIZE[1], self.tilemap.pixel_width, self.tilemap.pixel_height
        )
        self.enemies: list[Wanderer] = []
        self.altars: list[Altar] = []
        self.props: list[Entity] = []
        self.npcs: list[Npc] = []
        self.dialogue_bank = DialogueBank.load_default()
        self.altar_handler: Callable[[Altar], None] | None = None
        self.show_debug = True
        self.message = ""
        self.message_time = 0.0
        self.player = self._spawn_entities()
        self.camera.follow(*self.player.center)
        props = self.tilemap.data.properties
        self.area_name = str(props.get("area") or props.get("name") or self.map_path.stem)
        self._sync_altars()

    # ---- setup ------------------------------------------------------------------------
    def _spawn_entities(self) -> Player:
        data = self.tilemap.data
        spawn = data.first_object("player_spawn")
        player = Player(0, 0, sprites.sheet_tile(sprites.HERO))
        if spawn is not None:
            player.place_center(*spawn.center)
        else:
            player.place_center(self.tilemap.pixel_width / 2, self.tilemap.pixel_height / 2)
        self.spawn_point = player.center
        for obj in data.objects:
            if obj.type == "altar":
                tile = _tile_prop(obj, sprites.ALTAR)
                altar = Altar(
                    obj.x, obj.y, sprites.sheet_tile(tile) if tile is not None else None,
                    name=obj.name, properties=obj.properties,
                )
                self.altars.append(altar)
            elif obj.type == "enemy":
                tile = _tile_prop(obj, sprites.RED_SPIDER)
                enemy = Wanderer(
                    0, 0, sprites.sheet_tile(tile) if tile is not None else None,
                    hp=int(obj.properties.get("hp", 3)),
                    speed=float(obj.properties.get("speed", 30.0)),
                    name=obj.name, properties=obj.properties,
                )
                enemy.place_center(*obj.center)
                self.enemies.append(enemy)
            elif obj.type == "npc":
                tile = _tile_prop(obj, PROP_SPRITES["npc"])
                sprite = sprites.sheet_tile(tile) if tile is not None else None
                self.npcs.append(
                    Npc(obj.x, obj.y, sprite, name=obj.name, properties=obj.properties)
                )
            elif obj.type in ("chest", "door"):
                tile = _tile_prop(obj, PROP_SPRITES.get(obj.type))
                sprite = sprites.sheet_tile(tile) if tile is not None else None
                self.props.append(
                    StaticProp(obj.x, obj.y, sprite, name=obj.name, properties=obj.properties)
                )
        return player

    # ---- input ------------------------------------------------------------------------
    def move_vector(self) -> tuple[int, int]:
        """Sum of held move directions (each axis clamped to -1..1)."""
        dx = dy = 0
        for action in self.held:
            mx, my = MOVE_ACTIONS[action]
            dx += mx
            dy += my
        return (max(-1, min(1, dx)), max(-1, min(1, dy)))

    def handle_event(self, event: pygame.event.Event) -> None:
        """Translate key events to actions according to the current mode."""
        if event.type == pygame.WINDOWFOCUSLOST:
            self.held.clear()
            return
        if event.type == pygame.KEYUP:
            action = self.keymap.action_for_key(event.key)
            if action in MOVE_ACTIONS and action in self.held:
                self.held.remove(action)
            return
        if event.type != pygame.KEYDOWN:
            return
        if self.modes.mode is Mode.COMMAND:
            self._command_key(event)
            return
        unicode = getattr(event, "unicode", "")
        if unicode and self.modes.feed_digit(unicode):
            return
        action = self.keymap.action_for_key(event.key, unicode)
        if action is not None:
            self.do_action(action)

    def do_action(self, action: Action) -> None:
        """Perform a NORMAL-mode action (consumes any pending count)."""
        player = self.player
        if action in MOVE_ACTIONS:
            count = self.modes.pending_count
            if count is not None:
                self.modes.clear_count()
                player.dash_toward(MOVE_ACTIONS[action], count)
            elif action not in self.held:
                self.held.append(action)
        elif action is Action.ATTACK:
            player.attack(self.modes.take_count())
        elif action in (Action.DASH_FWD, Action.DASH_BACK):
            tiles = self.modes.pending_count
            self.modes.clear_count()
            player.dash(forward=action is Action.DASH_FWD, tiles=tiles)
        elif action is Action.INTERACT:
            self.modes.clear_count()
            altar = self.altar_in_reach()
            if altar is not None:
                self.on_altar(altar)
            else:
                self.talk_to_npc_in_reach()
        elif action is Action.ESCAPE:
            self.modes.escape()
        elif action is Action.COMMAND:
            self.modes.set_mode(Mode.COMMAND)
        elif action is Action.DEBUG:
            self.show_debug = not self.show_debug
        else:
            self.modes.clear_count()

    def _command_key(self, event: pygame.event.Event) -> None:
        if event.key == pygame.K_ESCAPE:
            self.modes.escape()
        elif event.key == pygame.K_BACKSPACE:
            self.modes.command_backspace()
        elif event.key in (pygame.K_RETURN, pygame.K_KP_ENTER):
            self.run_command(self.modes.command_submit())
        elif event.unicode and event.unicode.isprintable():
            self.modes.command_type(event.unicode)

    def run_command(self, command: str) -> None:
        """Execute a ``:`` command typed in the world."""
        if command in ("q", "quit", "q!", "qa"):
            self.game.quit()
        elif command == "set arrows":
            self.keymap = Keymap.default(arrows_fallback=True)
            self.flash("arrow keys + WASD enabled")
        elif command == "set noarrows":
            self.keymap = Keymap.default(arrows_fallback=False)
            self.flash("VIM keys only")
        elif command == "debug":
            self.show_debug = not self.show_debug
        elif command in ("save", "w"):
            self.save_game()
        elif command == "ledger":
            self.show_ledger()
        elif command:
            self.flash(f"E492: Not an editor command: {command}")

    def flash(self, text: str, seconds: float = 2.5) -> None:
        """Show a short message at the bottom of the screen."""
        self.message = text
        self.message_time = seconds

    # ---- altars -----------------------------------------------------------------------
    def altar_in_reach(self) -> Altar | None:
        """The altar whose interaction zone the player overlaps, if any."""
        for altar in self.altars:
            if boxes_overlap(self.player.box, altar.interact_box()):
                return altar
        return None

    def _sync_altars(self) -> None:
        """Light the altars whose puzzles are already solved in ``game.progress``."""
        progress = getattr(self.game, "progress", None)
        if progress is None or not self.altars:
            return
        from coderogue.altar import game_puzzles, resolve_puzzle_id
        from coderogue.puzzles import SpecError

        try:
            puzzles = game_puzzles(self.game)
        except SpecError:
            return
        for altar in self.altars:
            pid = resolve_puzzle_id(puzzles, altar.puzzle)
            altar.lit = pid is not None and progress.is_solved(pid)

    def on_altar(self, altar: Altar) -> None:
        """Player interacted with ``altar``: open the altar editor for its puzzle."""
        self.held.clear()
        if self.altar_handler is not None:
            self.altar_handler(altar)
            return
        from coderogue.altar import AltarScene, game_puzzles, resolve_puzzle_id
        from coderogue.progress import Progress
        from coderogue.puzzles import SpecError

        try:
            puzzles = game_puzzles(self.game)
        except SpecError as exc:
            self.flash(f"The altar's runes are garbled ({exc})")
            return
        pid = resolve_puzzle_id(puzzles, altar.puzzle)
        if pid is None:
            self.flash(f"The altar is silent (no puzzle {altar.puzzle!r}).")
            return
        progress = getattr(self.game, "progress", None)
        if progress is None:
            progress = Progress()
            self.game.progress = progress
        self.modes.set_mode(Mode.NORMAL)
        self.game.push(AltarScene(self.game, self, altar, puzzles[pid], progress))

    def on_puzzle_solved(self, spec: PuzzleSpec, result: PuzzleResult) -> None:
        """An altar's puzzle was solved: light every altar for it and announce the reward."""
        progress = getattr(self.game, "progress", None)
        if progress is not None:
            progress.flags.add(f"solved:{spec.id}")
            if spec.is_boss:
                saves = getattr(self.game, "saves", None)
                if saves is not None:
                    saves.tag_chapter(SAVE_SLOT, f"ch{spec.chapter}")
        self._sync_altars()
        effect = spec.reward.world_effect or "The altar lights."
        self.flash(effect, seconds=5.0)

    def on_puzzle_skipped(self, spec: PuzzleSpec) -> None:
        """The player skipped ``spec``: Pell's ghostly bridge spans the gap (altar stays unlit)."""
        self.flash("A ghostly Pell-bridge shimmers into place. The altar stays unlit.", 5.0)

    # ---- npcs and saving --------------------------------------------------------------
    def npc_in_reach(self) -> Npc | None:
        """The first NPC whose interact box overlaps the player, if any."""
        box = self.player.box
        return next((n for n in self.npcs if boxes_overlap(box, n.interact_box())), None)

    def talk_to_npc_in_reach(self) -> None:
        """Open the dialogue for the NPC in reach, picking the first line set whose flags fit."""
        npc = self.npc_in_reach()
        if npc is None:
            return
        flags = self.game.progress.flags
        dialogue = self.dialogue_bank.pick(npc.key, flags)
        if dialogue is None:
            self.flash(f"{npc.name} has nothing to say.")
            return
        self.held.clear()
        self.game.push(DialogueScene(self.game, dialogue))

    def save_state(self) -> SaveState:
        """Snapshot the world and progress for the save store."""
        p = self.player
        return SaveState(
            map=str(self.map_path),
            player=PlayerState(p.x, p.y, p.hp, getattr(p, "facing", "down")),
            progress=self.game.progress.to_dict(),
            area_name=self.area_name,
            waystone=self.area_name,
        )

    def save_game(self) -> None:
        """``:save``: write the slot and seal it in the Ledger (a git commit) when enabled."""
        saves = getattr(self.game, "saves", None)
        if saves is None:
            self.flash("No save store.")
            return
        receipt = saves.save(SAVE_SLOT, self.save_state())
        self.game.progress.flags.add("first_seal")
        if receipt.sha:
            self.flash(f"Sealed in the Ledger.  git commit -> {receipt.sha}", 4.0)
        else:
            self.flash("Saved.", 3.0)

    def show_ledger(self) -> None:
        """``:ledger``: show the last few seals (git log --oneline)."""
        saves = getattr(self.game, "saves", None)
        if saves is None:
            return
        ledger = saves.ledger(SAVE_SLOT)
        if not ledger.available:
            self.flash(saves.ledger_status(), 4.0)
            return
        entries = ledger.log(5)
        text = " | ".join(f"{e.sha} {e.message}" for e in entries) or "The Ledger is empty."
        self.flash(f"git log --oneline:  {text}", 6.0)

    # ---- simulation -------------------------------------------------------------------
    def update(self, dt: float) -> None:
        """One fixed step: player, enemies, combat, camera."""
        player = self.player
        move = self.move_vector() if self.modes.mode is Mode.NORMAL else (0, 0)
        player.update(dt, self, move=move)
        for altar in self.altars:
            altar.update(dt, self)
        for enemy in self.enemies:
            enemy.update(dt, self)
            if enemy.alive and boxes_overlap(player.box, enemy.box):
                player.hurt(enemy.contact_damage, enemy.center)
        box = player.attack_box()
        if box is not None:
            for enemy in self.enemies:
                key = id(enemy)
                if key not in player.struck and boxes_overlap(box, enemy.box):
                    player.struck.add(key)
                    enemy.hurt(1, player.center)
        self.enemies = [e for e in self.enemies if e.alive]
        if player.hp <= 0:
            player.hp = player.max_hp
            player.place_center(*self.spawn_point)
            self.flash("You wake at the spawn point.")
        if self.message_time > 0:
            self.message_time -= dt
        self.camera.follow(*player.center)

    # ---- rendering --------------------------------------------------------------------
    def draw(self, surface: pygame.Surface) -> None:
        """Render the world at 1x into the view, scale 3x nearest-neighbour, then overlay text."""
        view = self.view
        view.fill(BG_COLOR)
        offset = self.camera.offset
        self.tilemap.draw_below(view, offset)
        entities: list[Entity] = [
            *self.props, *self.npcs, *self.altars, *self.enemies, self.player
        ]
        for ent in sorted(entities, key=lambda e: e.bottom):
            ent.draw(view, offset)
        self.tilemap.draw_above(view, offset)
        pygame.transform.scale(view, surface.get_size(), surface)
        self._draw_overlay(surface)

    def _draw_overlay(self, surface: pygame.Surface) -> None:
        w, h = surface.get_size()
        draw_hud(
            surface, self.player, getattr(self.game, "progress", None), self.modes.mode,
            self.area_name,
        )
        if self.show_debug:
            px, py = self.player.center
            fps = self.game.clock.get_fps() if hasattr(self.game, "clock") else 0.0
            count = self.modes.count_text
            line = (
                f"FPS {fps:5.1f}{'  count ' + count if count else ''}"
                f"  pos {px:6.1f},{py:6.1f}"
            )
            width = render_text(line, 14).get_width()
            draw_text(surface, line, (w - width - 8, 6), size=14)
        if self.modes.mode is Mode.COMMAND:
            pygame.draw.rect(surface, (0, 0, 0), (0, h - 26, w, 26))
            draw_text(surface, ":" + self.modes.command_buffer + "_", (8, h - 22), size=16)
        elif self.message_time > 0 and self.message:
            draw_text(surface, self.message, (8, h - 24), size=16)
        elif self.altar_in_reach() is not None:
            draw_text(surface, "i / Enter: use altar", (8, h - 24), size=16, color=(160, 240, 200))
