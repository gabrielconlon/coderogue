"""The real-time world scene: map, player, enemies, altars, doors, waystones, items, camera
and the VIM-key world mechanics (lock-on, cleave, rewind, lift/put, search, marks).

One :class:`WorldScene` lives for the whole session; doors and fast travel swap the map in
place with :meth:`WorldScene.load_map`, so ``game.world``-style references stay valid.
"""

from __future__ import annotations

import dataclasses
import math
import os
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pygame

from coderogue.entities import combat, sprites
from coderogue.entities.altar import Altar
from coderogue.entities.base import Entity, StaticProp
from coderogue.entities.boss import Boss
from coderogue.entities.companion import Companion
from coderogue.entities.door import Door
from coderogue.entities.enemies import Enemy, StampGolem, spawn_enemy
from coderogue.entities.items import Chest, Pickup
from coderogue.entities.liftable import Liftable, Plate
from coderogue.entities.npc import Npc
from coderogue.entities.player import HURT_IFRAMES, Player
from coderogue.entities.waystone import WAYSTONE_TILE, Waystone, WaystoneMenu
from coderogue.input.keymap import MOVE_ACTIONS, Action, Keymap
from coderogue.input.modes import Mode, ModeMachine
from coderogue.save.store import PlayerState, SaveReceipt, SaveState
from coderogue.scene import Scene
from coderogue.story.dialogue import Dialogue, DialogueBank
from coderogue.story.scene import DialogueScene
from coderogue.ui import theme
from coderogue.ui.hud import draw_hud, draw_lock_glyph, draw_toast
from coderogue.ui.text import draw_text, render_text
from coderogue.world.camera import Camera
from coderogue.world.collision import boxes_overlap
from coderogue.world.loader import MapObject
from coderogue.world.tilemap import TileMap
from coderogue.world.transitions import (
    AreaCard,
    Fade,
    door_lock_reason,
    map_ref,
    resolve_map,
)

if TYPE_CHECKING:
    from coderogue.app import Game
    from coderogue.progress import Progress
    from coderogue.puzzles import PuzzleResult, PuzzleSpec

VIEW_SIZE = (320, 180)  # world pixels shown; scaled 3x to the 960x540 logical surface
SCALE = 3
BG_COLOR = (20, 16, 24)

PROP_SPRITES = {"npc": sprites.KNIGHT, "chest": sprites.CHEST}
SAVE_SLOT = "slot1"
MARKER_COLOR = (255, 225, 90)

# Default sprites for the Phase 5b objects (Tiny Dungeon ids unless noted).
DOOR_TILE = 45
CHEST_OPEN_TILE = 91
POTION_TILE = 115  # red flask
COIN_TILE = 93  # Tiny Town gold coin
LIFTABLE_TILE = 63  # wooden crate

LOCK_RANGE = 6 * 16  # v locks on to the nearest bug within 6 tiles
CYCLE_RANGE = 10 * 16  # hjkl in VISUAL cycles among bugs within 10 tiles
COMBAT_RANGE = 6 * 16  # marks refuse to fast-travel with a bug this close
SEQUENCE_WINDOW = 0.4  # seconds between the two keys of dd / yy
CLEAVE_DAMAGE = 1
SEARCH_FOCUS_TIME = 1.2  # n pans the camera to the match for this long
VISUAL_COLOR = (150, 140, 240)
SEARCH_COLOR = (240, 200, 110)

#: Each gated mechanic and the story flag (set by its teaching dialogue) that unlocks it.
#: ``world.unlocked`` is derived from these flags; see :meth:`WorldScene.refresh_unlocks`.
UNLOCK_FLAGS: dict[str, str] = {
    "dash": "learned_w",  # Pip, Echo Vale
    "counts": "learned_counts",  # Tally's crow letter, Branchwood
    "visual": "learned_v",  # Sable, Branchwood
    "cleave": "learned_dd",  # Tally's crow letter, Branchwood (the Loopers' row)
    "rewind": "got_hourglass",  # Ono, the Looping Mire
    "yank": "learned_yank",  # Dex, the Grand Directory
    "search": "learned_search",  # Dex, the Grand Directory
    "marks": "learned_marks",  # Cole, the Grand Directory
}
ALL_MECHANICS = frozenset(UNLOCK_FLAGS)
#: Never locked: walking, ``x``, ``i``, ``Esc`` and the ``:`` command line.
BASE_MECHANICS = frozenset({"move", "strike", "interact", "escape", "command"})
#: The in-world flash when a locked mechanic's key is pressed.
LOCKED_LINES: dict[str, str] = {
    "dash": "Your feet don't know the Runner's Stride yet.",
    "counts": "Count before you act, says Tally. You haven't met Tally's letter yet.",
    "visual": "You have not found the Spyglass yet.",
    "cleave": "The Cleave is a lesson of the Branchwood road.",
    "rewind": "You have no hourglass.",
    "yank": "Dex has not shown you the yank.",
    "search": "The Directory's search is still unknown to you.",
    "marks": "Cole has not taught you marks.",
}
#: Keys and name shown on the "New stance learned" toast.
UNLOCK_TOASTS: dict[str, str] = {
    "dash": "w / b / e  dash",
    "counts": "3j / 3x  counts",
    "visual": "v  lock on",
    "cleave": "dd  cleave",
    "rewind": "u  rewind",
    "yank": "yy / p  yank and put",
    "search": "/ and n  search",
    "marks": "m / '  marks",
}
TOAST_TIME = 3.0
ALL_UNLOCKED_ENV = "CODEROGUE_ALL_UNLOCKED"

FACING_NAMES = {(0, 1): "down", (0, -1): "up", (-1, 0): "left", (1, 0): "right"}
NAMED_FACINGS = {v: k for k, v in FACING_NAMES.items()}

KILL_XP = 5  # XP awarded per bug struck out


def _tile_prop(obj: MapObject, default: int | None) -> int | None:
    value = obj.properties.get("tile", obj.properties.get("sprite", default))
    return int(value) if value is not None else None


def _sprite_for(
    obj: MapObject, default: int | None, sheet: tuple[str, ...] = sprites.DUNGEON_SHEET
) -> pygame.Surface | None:
    """Sprite from the object's ``tile`` (and optional ``sheet``: dungeon/town) property."""
    tile = _tile_prop(obj, default)
    if tile is None:
        return None
    which = str(obj.properties.get("sheet") or "").lower()
    if which == "town":
        sheet = sprites.TOWN_SHEET
    elif which == "dungeon":
        sheet = sprites.DUNGEON_SHEET
    return sprites.sheet_tile(tile, sheet)


def _boss_object(obj: MapObject) -> MapObject:
    """Map ``kind=boss`` + ``boss=<name>`` to ``spawn_enemy``'s boss kind (``kind=<name>``)."""
    props = obj.properties
    if str(props.get("kind", "")).lower() == "boss" and props.get("boss"):
        return dataclasses.replace(obj, properties={**props, "kind": str(props["boss"])})
    return obj


def altar_phase(altar: Altar) -> int | None:
    """The boss phase an altar (lectern) opens: ``phase`` property ``a``/``b``/... or 0-based
    int; None when unset."""
    raw = altar.properties.get("phase")
    if raw is None or raw == "":
        return None
    text = str(raw).strip().lower()
    if text.isdigit():
        return int(text)
    if len(text) == 1 and "a" <= text <= "z":
        return ord(text) - ord("a")
    return None


def _dist(a: Entity, b: Entity) -> float:
    ax, ay = a.center
    bx, by = b.center
    return math.hypot(ax - bx, ay - by)


class WorldScene(Scene):
    """Top-down real-time play.

    Pressing INTERACT (``i`` / Enter) at an altar calls :meth:`on_altar`, which by default
    pushes an :class:`~coderogue.altar.AltarScene` for the altar's puzzle. Set
    ``altar_handler`` (or override :meth:`on_altar`) to replace that. When a puzzle is solved
    the altar scene calls :meth:`on_puzzle_solved` (and :meth:`on_puzzle_skipped` on a skip).

    Combat hooks used by ``coderogue.entities.combat``: ``enemies``, ``player``,
    ``locked_target``, :meth:`on_enemy_killed` and :meth:`spawn_enemy_instance`.
    """

    def __init__(
        self,
        game: Game,
        map_path: str | Path,
        keymap: Keymap | None = None,
        spawn: str | None = None,
    ) -> None:
        super().__init__(game)
        arrows = bool(getattr(game, "arrows_fallback", False))
        self.keymap = keymap or Keymap.default(arrows_fallback=arrows)
        self.modes = ModeMachine()
        self.held: list[Action] = []  # held move actions, in press order
        self.view = pygame.Surface(VIEW_SIZE).convert() if pygame.display.get_surface() else (
            pygame.Surface(VIEW_SIZE)
        )
        self.dialogue_bank = DialogueBank.load_default()
        self.altar_handler: Callable[[Altar], None] | None = None
        self.show_debug = True
        self.show_help = False
        self.companion: Companion | None = None
        self.marker_clock = 0.0
        self.message = ""
        self.message_time = 0.0
        self.time = 0.0
        self.fade = Fade()
        self.area_card = AreaCard()
        self.player = Player(0, 0, sprites.sheet_tile(sprites.HERO))
        # persistent across maps
        self.last_waystone: tuple[str, str] | None = None
        self.marks: dict[str, tuple[str, str]] = {}
        self.visited_waystones: set[tuple[str, str]] = set()
        self.unlocked: set[str] = set(BASE_MECHANICS)
        self.toast: str | None = None  # "New stance learned" banner text
        self.toast_time = 0.0
        self.toast_queue: list[str] = []
        # VIM mechanics state
        self.locked_target: Enemy | None = None
        self.search_input: str | None = None  # text being typed after "/"
        self.search_term = ""
        self.search_matches: list[Entity] = []
        self.search_index = -1
        self.focus: Entity | None = None
        self.focus_time = 0.0
        self.pending_key: str | None = None  # "m" / "'" waiting for a letter
        self._pending_op: tuple[str, float] | None = None  # ("d" | "y", time)
        self._alias_cache: dict[str, str | None] = {}
        # crates put down, per map: {map_key: {crate_key: [tile_x, tile_y]}} (saved in extras)
        self.crates: dict[str, dict[str, list[int]]] = {}
        # map-triggered dialogue (boss intro/defeat), pushed once the world is on top
        self.queued_dialogue: list[Dialogue] = []
        self.refresh_unlocks(announce=False)
        self.load_map(map_path, spawn)

    # ---- maps -------------------------------------------------------------------------
    @property
    def map_key(self) -> str:
        """Reference of the current map (stem for bundled maps)."""
        return map_ref(self.map_path)

    def load_map(
        self,
        target: str | Path,
        spawn: str | None = None,
        waystone: str | None = None,
        show_card: bool = True,
    ) -> None:
        """Load ``target`` (map stem or path) in place and put the hero at the
        ``player_spawn`` named ``spawn`` (or at the waystone named ``waystone``)."""
        path = resolve_map(target)
        carried = self.player.carrying
        if isinstance(carried, Liftable) and hasattr(self, "map_path"):
            # a crate carried out of a map goes home to its origin there
            self.crates.get(self.map_key, {}).pop(carried.key, None)
        self.map_path = path
        self.tilemap = TileMap.load(path)
        self.collision = self.tilemap.collision
        self._base_solid = list(self.collision.solid)
        self._solid_sig: tuple[Any, ...] | None = None
        self.camera = Camera(
            VIEW_SIZE[0], VIEW_SIZE[1], self.tilemap.pixel_width, self.tilemap.pixel_height
        )
        self.enemies: list[Enemy] = []
        self.altars: list[Altar] = []
        self.props: list[Entity] = []
        self.npcs: list[Npc] = []
        self.doors: list[Door] = []
        self.waystones: list[Waystone] = []
        self.chests: list[Chest] = []
        self.pickups: list[Pickup] = []
        self.liftables: list[Liftable] = []
        self.plates: list[Plate] = []
        self._killed: set[int] = set()
        self._touching: Door | None = None
        self._door_armed = False  # doors fire only after the hero first steps off them
        self.held.clear()
        self.player.carrying = None  # a carried object stays behind in the old map
        self.player.trail.clear()
        self.player.rewind_path = []
        self.locked_target = None
        if self.modes.mode is Mode.VISUAL:
            self.modes.escape()
        self.clear_search()
        self._populate()
        self._apply_crates()
        self._place_player(spawn, waystone)
        props = self.tilemap.data.properties
        self.area_name = str(props.get("area") or props.get("name") or path.stem)
        enter_flag = props.get("enter_flag")
        if enter_flag:
            self._progress().flags.add(str(enter_flag))
        self.refresh_unlocks()
        if self.companion is not None:
            self.companion.reset()
        self.dismiss_golems()
        self.queued_dialogue.clear()
        intro = props.get("intro_dialogue")
        if intro:
            self.queue_dialogue(str(intro))
        self._update_world_state()
        self.camera.follow(*self.player.center)
        self._sync_altars()
        if show_card:
            self.area_card.show(self.area_name)

    def _place_player(self, spawn: str | None, waystone: str | None) -> None:
        data = self.tilemap.data
        point: tuple[float, float] | None = None
        if waystone:
            ws = next((w for w in self.waystones if w.name == waystone), None)
            if ws is not None:
                point = ws.stand_point
        if point is None:
            spawns = data.objects_of_type("player_spawn")
            named = next((o for o in spawns if spawn and o.name == spawn), None)
            chosen = named or (spawns[0] if spawns else None)
            if chosen is not None:
                point = chosen.center
        if point is None:
            point = (self.tilemap.pixel_width / 2, self.tilemap.pixel_height / 2)
        self.player.place_center(*point)
        self.spawn_point = self.player.center

    def _obj_key(self, obj: MapObject) -> str:
        return f"{self.map_key}#{obj.id}"

    def _populate(self) -> None:
        flags = self._progress().flags
        ref = self.map_key
        for obj in self.tilemap.data.objects:
            kind = obj.type
            if kind == "altar":
                self.altars.append(Altar(
                    obj.x, obj.y, _sprite_for(obj, sprites.ALTAR),
                    name=obj.name, properties=obj.properties,
                ))
            elif kind == "enemy":
                self.enemies.append(spawn_enemy(_boss_object(obj), sprites))
            elif kind == "npc":
                self.npcs.append(Npc(
                    obj.x, obj.y, _sprite_for(obj, PROP_SPRITES["npc"]),
                    name=obj.name, properties=obj.properties,
                ))
            elif kind == "door":
                self.doors.append(Door(
                    obj.x, obj.y, obj.width, obj.height, _sprite_for(obj, DOOR_TILE),
                    name=obj.name, properties=obj.properties,
                ))
            elif kind == "chest":
                chest = Chest(
                    obj.x, obj.y, _sprite_for(obj, sprites.CHEST),
                    sprites.sheet_tile(CHEST_OPEN_TILE), name=obj.name,
                    properties=obj.properties,
                )
                chest.obj_key = self._obj_key(obj)  # type: ignore[attr-defined]
                if f"opened:{chest.obj_key}" in flags:  # type: ignore[attr-defined]
                    chest.open()
                self.chests.append(chest)
            elif kind in ("potion", "coin"):
                key = self._obj_key(obj)
                if f"taken:{key}" in flags:
                    continue
                default = POTION_TILE if kind == "potion" else COIN_TILE
                sheet = sprites.TOWN_SHEET if kind == "coin" else sprites.DUNGEON_SHEET
                pickup = Pickup(0, 0, kind, _sprite_for(obj, default, sheet), name=obj.name,
                                properties=obj.properties)
                pickup.place_center(*obj.center)
                pickup.obj_key = key  # type: ignore[attr-defined]
                self.pickups.append(pickup)
            elif kind == "waystone":
                ws = Waystone(
                    obj.x, obj.y, _sprite_for(obj, WAYSTONE_TILE, sprites.TOWN_SHEET),
                    name=obj.name or f"waystone#{obj.id}", properties=obj.properties,
                )
                ws.visited = (ref, ws.name) in self.visited_waystones
                self.waystones.append(ws)
            elif kind == "liftable":
                lift = Liftable(obj.x, obj.y, _sprite_for(obj, LIFTABLE_TILE),
                                name=obj.name, properties=obj.properties)
                lift.key = obj.name or f"#{obj.id}"
                lift.place_on_tile(*lift.tile(self.tilemap.tile_size), self.tilemap.tile_size)
                self.liftables.append(lift)
            elif kind == "plate":
                sprite = _sprite_for(obj, None) if "tile" in obj.properties else None
                self.plates.append(Plate(obj.x, obj.y, sprite, name=obj.name,
                                         properties=obj.properties))
            elif kind == "prop":
                self.props.append(StaticProp(
                    obj.x, obj.y, _sprite_for(obj, None), name=obj.name,
                    properties=obj.properties,
                ))

    def all_entities(self) -> list[Entity]:
        """Every entity in the map except the hero (draw order not applied)."""
        return [
            *self.plates, *self.props, *self.doors, *self.waystones, *self.chests,
            *self.pickups, *self.liftables, *self.npcs, *self.altars, *self.enemies,
        ]

    def travel(
        self, target: str | Path, spawn: str | None = None, waystone: str | None = None
    ) -> bool:
        """Fade out, move to ``target`` (reloading only if it is another map), fade in."""
        self.held.clear()
        return self.fade.start(lambda: self._arrive(target, spawn, waystone))

    def _arrive(self, target: str | Path, spawn: str | None, waystone: str | None) -> None:
        if resolve_map(target).resolve() != self.map_path.resolve():
            self.load_map(target, spawn, waystone)
            return
        self._place_player(spawn, waystone)
        self.player.trail.clear()
        self._door_armed = False
        self.camera.follow(*self.player.center)

    # ---- progress helpers -------------------------------------------------------------
    def _progress(self) -> Progress:
        progress = getattr(self.game, "progress", None)
        if progress is None:
            from coderogue.progress import Progress

            progress = Progress()
            self.game.progress = progress
        return progress

    # ---- unlocks ----------------------------------------------------------------------
    def all_unlocked(self) -> bool:
        """Dev escape: ``game.dev_all_unlocked`` or ``CODEROGUE_ALL_UNLOCKED=1``."""
        if getattr(self.game, "dev_all_unlocked", False) is True:
            return True
        return os.environ.get(ALL_UNLOCKED_ENV, "") == "1"

    def compute_unlocked(self) -> set[str]:
        """The base mechanics plus every mechanic whose :data:`UNLOCK_FLAGS` flag is set."""
        if self.all_unlocked():
            return set(BASE_MECHANICS | ALL_MECHANICS)
        flags = self._progress().flags
        return set(BASE_MECHANICS) | {m for m, flag in UNLOCK_FLAGS.items() if flag in flags}

    def _refresh_companion(self) -> None:
        """Moth tags along once ``moth_joined`` is set; the static Moth npc then steps aside."""
        if "moth_joined" not in self._progress().flags:
            return
        if self.companion is None:
            self.companion = Companion.moth()
        for npc in self.npcs:
            if npc.key == "moth":
                npc.visible = False

    def refresh_unlocks(self, announce: bool = True) -> list[str]:
        """Re-derive :attr:`unlocked` from the progress flags; returns the newly unlocked
        mechanics (in teaching order) and, if ``announce``, queues a toast for each."""
        new = self.compute_unlocked()
        self._refresh_companion()
        gained = [m for m in UNLOCK_FLAGS if m in new and m not in self.unlocked]
        self.unlocked = new
        if announce:
            for mechanic in gained:
                self.show_toast(f"New stance learned: {UNLOCK_TOASTS[mechanic]}")
        return gained

    def show_toast(self, text: str) -> None:
        """Queue a centered banner; banners show one at a time for ``TOAST_TIME`` s."""
        if self.toast is None:
            self.toast, self.toast_time = text, TOAST_TIME
        else:
            self.toast_queue.append(text)

    def _update_toast(self, dt: float) -> None:
        if self.toast is None:
            return
        self.toast_time -= dt
        if self.toast_time <= 0:
            if self.toast_queue:
                self.toast, self.toast_time = self.toast_queue.pop(0), TOAST_TIME
            else:
                self.toast, self.toast_time = None, 0.0

    def locked(self, mechanic: str) -> bool:
        """True (after flashing the in-world line) when ``mechanic`` is not yet learned."""
        if mechanic in self.unlocked:
            return False
        self.flash(LOCKED_LINES.get(mechanic, "You have not learned that yet."))
        return True

    def on_resume(self) -> None:
        """Back on top (a dialogue, altar or menu closed): pick up any new unlocks."""
        self.refresh_unlocks()

    def _is_solved(self, ref: str) -> bool:
        progress = self._progress()
        if progress.is_solved(ref):
            return True
        if ref not in self._alias_cache:
            pid: str | None = None
            try:
                from coderogue.altar import game_puzzles, resolve_puzzle_id

                pid = resolve_puzzle_id(game_puzzles(self.game), ref)
            except Exception:  # noqa: BLE001 - a broken puzzle set must not break doors
                pid = None
            self._alias_cache[ref] = pid
        alias = self._alias_cache[ref]
        return alias is not None and progress.is_solved(alias)

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
        if event.type != pygame.KEYDOWN or self.fade.active:
            return
        if self.search_input is not None:
            self._search_key(event)
            return
        if self.modes.mode is Mode.COMMAND:
            self._command_key(event)
            return
        unicode = getattr(event, "unicode", "")
        if self.pending_key is not None:
            self._pending_letter(unicode)
            return
        if (
            len(unicode) == 1 and unicode in "123456789" and not self.modes.pending_count
            and self.modes.mode in (Mode.NORMAL, Mode.VISUAL) and self.locked("counts")
        ):
            return
        if unicode and self.modes.feed_digit(unicode):
            return
        action = self.keymap.action_for_key(event.key, unicode)
        if action is not None:
            self.do_action(action)

    def _pending_letter(self, unicode: str) -> None:
        key, self.pending_key = self.pending_key, None
        if len(unicode) != 1 or not unicode.isalpha() or not unicode.isascii():
            return  # Esc or anything else cancels
        if key == "m":
            self.set_mark(unicode)
        else:
            self.jump_to_mark(unicode)

    def _sequence(self, op: str) -> bool:
        """Second press of ``op`` within ``SEQUENCE_WINDOW``? (``dd``, ``yy``)."""
        pending = self._pending_op
        if pending is not None and pending[0] == op and self.time - pending[1] <= SEQUENCE_WINDOW:
            self._pending_op = None
            return True
        self._pending_op = (op, self.time)
        return False

    def do_action(self, action: Action) -> None:
        """Perform an action in NORMAL or VISUAL mode (consumes any pending count)."""
        player = self.player
        if action not in (Action.DELETE, Action.YANK):
            self._pending_op = None
        if self.modes.mode is Mode.VISUAL and action in MOVE_ACTIONS:
            self.modes.clear_count()
            self.cycle_target(MOVE_ACTIONS[action])
            return
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
            if self.locked("dash"):
                return
            player.dash(forward=action is Action.DASH_FWD, tiles=tiles)
        elif action is Action.INTERACT:
            self.modes.clear_count()
            self.interact()
        elif action is Action.ESCAPE:
            self.show_help = False
            self.escape()
        elif action is Action.COMMAND:
            self.modes.set_mode(Mode.COMMAND)
        elif action is Action.VISUAL:
            self.modes.clear_count()
            self.toggle_visual()
        elif action is Action.UNDO:
            self.modes.clear_count()
            self.rewind()
        elif action is Action.DELETE:
            self.modes.clear_count()
            if self._sequence("d"):
                self.cleave()
        elif action is Action.YANK:
            self.modes.clear_count()
            if self._sequence("y"):
                self.lift()
        elif action is Action.PUT:
            self.modes.clear_count()
            self.put()
        elif action is Action.SEARCH:
            self.modes.clear_count()
            self.start_search()
        elif action is Action.SEARCH_NEXT:
            self.modes.clear_count()
            if not self.locked("search"):
                self.search_next()
        elif action in (Action.MARK, Action.JUMP_MARK):
            self.modes.clear_count()
            if not self.locked("marks"):
                self.pending_key = "m" if action is Action.MARK else "'"
        elif action is Action.DEBUG:
            self.show_debug = not self.show_debug
        elif action is Action.HELP:
            self.show_help = not self.show_help
        else:
            self.modes.clear_count()

    def escape(self) -> None:
        """``Esc``: back to NORMAL, dropping lock-on, search highlights and pending keys."""
        self.modes.escape()
        self.locked_target = None
        self.pending_key = None
        self._pending_op = None
        self.clear_search()

    def interact(self) -> None:
        """INTERACT: altar, then waystone, then chest, then NPC in reach."""
        altar = self.altar_in_reach()
        if altar is not None:
            self.on_altar(altar)
            return
        ws = self.waystone_in_reach()
        if ws is not None:
            self.use_waystone(ws)
            return
        chest = self.chest_in_reach()
        if chest is not None:
            self.open_chest(chest)
            return
        self.talk_to_npc_in_reach()

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
        elif command == "marks":
            text = "  ".join(f"'{k} {v[1]}" for k, v in sorted(self.marks.items()))
            self.flash(text or "No marks set.", 4.0)
        elif command:
            self.flash(f"E492: Not an editor command: {command}")

    def flash(self, text: str, seconds: float = 2.5) -> None:
        """Show a short message at the bottom of the screen."""
        self.message = text
        self.message_time = seconds

    # ---- VISUAL lock-on ---------------------------------------------------------------
    def lockable_targets(self) -> list[Entity]:
        """Everything ``v`` may lock on to: living enemies plus a boss's live children
        (crown letters, worm segments)."""
        out: list[Entity] = []
        for enemy in self.enemies:
            if not enemy.alive:
                continue
            if isinstance(enemy, Boss):
                out.extend(enemy.targets())
            else:
                out.append(enemy)
        return out

    def nearest_enemy(self, max_dist: float) -> Entity | None:
        """The lockable target nearest the hero within ``max_dist`` px, or None. A glowing
        target (the Ouroboros segment that may be cleaved) wins over anything nearer."""
        best: Entity | None = None
        best_key = (1, max_dist)
        for target in self.lockable_targets():
            d = _dist(self.player, target)
            if d > max_dist:
                continue
            key = (0 if getattr(target, "glowing", False) else 1, d)
            if key <= best_key:
                best, best_key = target, key
        return best

    def toggle_visual(self) -> None:
        """``v``: lock on to the nearest bug (VISUAL), or release back to NORMAL."""
        if self.modes.mode is Mode.VISUAL:
            self.exit_visual()
            return
        if self.locked("visual"):
            return
        target = self.nearest_enemy(LOCK_RANGE)
        if target is None:
            self.flash("Nothing to lock on to.")
            return
        self.locked_target = target
        self.held.clear()
        self.modes.set_mode(Mode.VISUAL)

    def exit_visual(self) -> None:
        """Leave VISUAL and drop the lock."""
        self.locked_target = None
        if self.modes.mode is Mode.VISUAL:
            self.modes.set_mode(Mode.NORMAL)

    def cycle_target(self, direction: tuple[int, int]) -> Enemy | None:
        """Lock on to the next bug in ``direction`` from the current target."""
        current = self.locked_target
        if current is None:
            return None
        cx, cy = current.center
        dx, dy = direction
        best, best_score = None, math.inf
        for enemy in self.lockable_targets():
            if enemy is current or _dist(self.player, enemy) > CYCLE_RANGE:
                continue
            ex, ey = enemy.center
            vx, vy = ex - cx, ey - cy
            along = vx * dx + vy * dy
            if along <= 0:
                continue
            across = abs(vx * dy - vy * dx)
            score = along + 2 * across
            if score < best_score:
                best, best_score = enemy, score
        if best is not None:
            self.locked_target = best
        return self.locked_target

    def _check_lock(self) -> None:
        target = self.locked_target
        if target is None:
            if self.modes.mode is Mode.VISUAL:
                self.modes.set_mode(Mode.NORMAL)
            return
        if (
            target.alive and target in self.lockable_targets()
            and _dist(self.player, target) <= CYCLE_RANGE
        ):
            return
        replacement = self.nearest_enemy(LOCK_RANGE)
        if replacement is not None and self.modes.mode is Mode.VISUAL:
            self.locked_target = replacement
        else:
            self.exit_visual()

    # ---- combat hooks -----------------------------------------------------------------
    def on_enemy_killed(self, enemy: Enemy) -> None:
        """A bug died: award XP (and its ``coins``, if any). Safe to call twice."""
        if id(enemy) in self._killed:
            return
        self._killed.add(id(enemy))
        self._progress().xp += KILL_XP
        self.player.coins += int(getattr(enemy, "coins", 0) or 0)
        if self.locked_target is enemy:
            self._check_lock()
        if isinstance(enemy, Boss):
            # The boss falls after its last phase: on_puzzle_solved already set
            # ``solved:<id>``, so the defeat lines (``requires: [solved:<id>]``) pick here.
            defeat = self.tilemap.data.properties.get("defeat_dialogue")
            if defeat:
                self.queue_dialogue(str(defeat))

    def spawn_enemy_instance(self, enemy: Enemy) -> None:
        """Add an enemy created during the step (a Leak splitting, a boss summon)."""
        self.enemies.append(enemy)

    def cleave(self) -> bool:
        """``dd``: hit every bug in the hero's row/column (8 tiles each side)."""
        if self.locked("cleave"):
            return False
        box = self.player.cleave()
        if box is None:
            return False
        combat.resolve_player_attacks(self, box, CLEAVE_DAMAGE, "cleave", struck=set())
        return True

    def rewind(self) -> bool:
        """``u``: rewind 3 s of movement (one hourglass charge)."""
        if self.locked("rewind"):
            return False
        if self.player.rewind():
            return True
        if self.player.u_charges <= 0:
            self.flash("The hourglass is empty. Rest at a waystone.")
        return False

    def in_combat(self) -> bool:
        """True when a living bug is within ``COMBAT_RANGE`` of the hero."""
        return self.nearest_enemy(COMBAT_RANGE) is not None

    # ---- lift / put -------------------------------------------------------------------
    def front_tile(self) -> tuple[int, int]:
        """The tile directly in front of the hero (never one the hero overlaps)."""
        ts = self.tilemap.tile_size
        cx, cy = self.player.center
        fx, fy = self.player.facing
        tx, ty = int((cx + fx * ts) // ts), int((cy + fy * ts) // ts)
        if boxes_overlap(self.player.box, (tx * ts, ty * ts, ts, ts)):
            tx, ty = tx + fx, ty + fy
        return (tx, ty)

    def _tile_free(self, tx: int, ty: int) -> bool:
        ts = self.tilemap.tile_size
        if self.collision.is_solid(tx, ty):
            return False
        rect = (tx * ts, ty * ts, ts, ts)
        blockers: list[Entity] = [
            self.player, *self.npcs, *self.altars, *self.waystones, *self.chests,
            *self.doors, *self.liftables, *self.enemies,
        ]
        return not any(boxes_overlap(rect, e.box) for e in blockers if e.alive)

    def liftable_in_reach(self) -> Liftable | None:
        """The liftable in front of the hero, else any one touching the hero."""
        ts = self.tilemap.tile_size
        front = self.front_tile()
        for lift in self.liftables:
            if lift.tile(ts) == front:
                return lift
        px, py, pw, ph = self.player.box
        reach = (px - 4, py - 4, pw + 8, ph + 8)
        return next((lift for lift in self.liftables if boxes_overlap(reach, lift.box)), None)

    def lift(self) -> bool:
        """``yy``: pick up the adjacent liftable and carry it overhead."""
        if self.locked("yank"):
            return False
        if self.player.carrying is not None:
            self.flash("Your hands are full. p puts it down.")
            return False
        target = self.liftable_in_reach()
        if target is None:
            self.flash("Nothing to yank here.")
            return False
        self.liftables.remove(target)
        self.player.carrying = target
        self._update_world_state()
        return True

    def put(self) -> bool:
        """``p``: put the carried object on the tile in front, if it is free."""
        carried = self.player.carrying
        if carried is None:
            self.flash("Nothing to put.")
            return False
        tx, ty = self.front_tile()
        if not self._tile_free(tx, ty):
            self.flash("No room to put it there.")
            return False
        assert isinstance(carried, Liftable)
        carried.place_on_tile(tx, ty, self.tilemap.tile_size)
        self.liftables.append(carried)
        self.player.carrying = None
        if carried.key:
            self.crates.setdefault(self.map_key, {})[carried.key] = [tx, ty]
        self._update_world_state()
        return True

    def _apply_crates(self) -> None:
        """Move this map's crates to where they were last put down (see :attr:`crates`)."""
        placed = self.crates.get(self.map_key, {})
        ts = self.tilemap.tile_size
        for lift in self.liftables:
            pos = placed.get(lift.key)
            if pos is not None:
                lift.place_on_tile(int(pos[0]), int(pos[1]), ts)

    # ---- search -----------------------------------------------------------------------
    def start_search(self) -> None:
        """``/``: open the search prompt."""
        if self.locked("search"):
            return
        self.held.clear()
        self.search_input = ""

    def _search_key(self, event: pygame.event.Event) -> None:
        text = self.search_input or ""
        if event.key == pygame.K_ESCAPE:
            self.search_input = None
        elif event.key == pygame.K_BACKSPACE:
            self.search_input = text[:-1] if text else None
        elif event.key in (pygame.K_RETURN, pygame.K_KP_ENTER):
            self.search_input = None
            self.search(text)
        elif event.unicode and event.unicode.isprintable():
            self.search_input = text + event.unicode

    def search(self, term: str) -> int:
        """Highlight every entity whose name contains ``term``; returns the match count."""
        term = term.strip()
        if not term:
            self.clear_search()
            return 0
        low = term.lower()
        matches = [e for e in self.all_entities() if e.name and low in e.name.lower()]
        matches.sort(key=lambda e: _dist(self.player, e))
        self.search_term = term
        self.search_matches = matches
        self.search_index = -1
        if matches:
            self.flash(f"/{term}: {len(matches)} match{'es' if len(matches) != 1 else ''}"
                       "  (n: next)")
        else:
            self.flash(f"E486: Pattern not found: {term}")
        return len(matches)

    def search_next(self) -> Entity | None:
        """``n``: focus the camera (and the arrow) on the next match."""
        self.search_matches = [e for e in self.search_matches if e.alive]
        if not self.search_matches:
            self.flash("E35: No previous regular expression" if not self.search_term
                       else f"E486: Pattern not found: {self.search_term}")
            return None
        self.search_index = (self.search_index + 1) % len(self.search_matches)
        match = self.search_matches[self.search_index]
        self.focus = match
        self.focus_time = SEARCH_FOCUS_TIME
        self.flash(f"/{self.search_term} [{self.search_index + 1}/"
                   f"{len(self.search_matches)}] {match.name}")
        return match

    @property
    def current_match(self) -> Entity | None:
        """The match ``n`` last moved to, if any."""
        if 0 <= self.search_index < len(self.search_matches):
            return self.search_matches[self.search_index]
        return None

    def clear_search(self) -> None:
        """Drop highlights and the search prompt."""
        self.search_input = None
        self.search_term = ""
        self.search_matches = []
        self.search_index = -1
        self.focus = None
        self.focus_time = 0.0

    # ---- marks ------------------------------------------------------------------------
    def set_mark(self, letter: str) -> bool:
        """``m{a-z}``: remember the waystone the hero stands at under ``letter``."""
        ws = self.waystone_in_reach()
        if ws is None:
            self.flash("Marks can only be set at a waystone.")
            return False
        self.marks[letter] = (self.map_key, ws.name)
        self.flash(f"Mark '{letter} set at {ws.name}.")
        return True

    def jump_to_mark(self, letter: str) -> bool:
        """``'{a-z}``: fast-travel to a marked waystone (not while bugs are near)."""
        mark = self.marks.get(letter)
        if mark is None:
            self.flash(f"E20: Mark not set: '{letter}")
            return False
        if self.in_combat():
            self.flash("Not while bugs are near.")
            return False
        ref, name = mark
        return self.travel(ref, waystone=name)

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
        spec = puzzles[pid]
        phase: int | None = None
        if spec.is_boss:
            phase = altar_phase(altar)
            boss = self.active_boss()
            if boss is not None:
                index = phase if phase is not None else boss.next_unsolved()
                if index is not None and index in boss.solved:
                    self.flash("This lectern's phase is already won.")
                    return
                if index is None or not boss.open_lectern(index):
                    self.flash(f"{boss.name or 'The boss'} is too wild. Stun it first!")
                    return
                phase = index
        progress = self._progress()
        self.modes.set_mode(Mode.NORMAL)
        self.locked_target = None
        single = phase is not None and 0 <= phase < len(spec.phases)
        scene = AltarScene(
            self.game, self, altar, spec, progress,
            start_phase=phase if single else None, single_phase=single,
        )
        self.game.push(scene)

    def active_boss(self) -> Boss | None:
        """The living boss in this map, if any."""
        return next(
            (e for e in self.enemies if isinstance(e, Boss) and e.alive and not e.dying), None
        )

    def on_boss_phase_solved(self, spec: PuzzleSpec, phase_index: int) -> None:
        """A boss altar reports phase ``phase_index`` solved: tell the boss."""
        boss = self.active_boss()
        if boss is not None:
            boss.phase_solved(phase_index)

    def on_puzzle_solved(self, spec: PuzzleSpec, result: PuzzleResult) -> None:
        """An altar's puzzle was solved: light every altar for it and announce the reward."""
        progress = getattr(self.game, "progress", None)
        if spec.is_boss:
            for i in range(len(spec.phases)):  # idempotent with on_boss_phase_solved
                self.on_boss_phase_solved(spec, i)
        effect = spec.reward.world_effect or "The altar lights."
        if progress is not None:
            progress.flags.add(f"solved:{spec.id}")
            self.dismiss_golems()
            if spec.is_boss:
                # Seal first, so the chapter tag points at a save made after the win.
                tag = f"ch{spec.chapter}"
                receipt = self._seal(f"Chapter {spec.chapter}: {spec.id} solved")
                saves = getattr(self.game, "saves", None)
                if receipt is not None and saves is not None:
                    if saves.tag_chapter(SAVE_SLOT, tag):
                        effect += f"  (Sealed in the Ledger as {tag}.)"
                    else:
                        effect += "  (Saved.)"
        self._sync_altars()
        self.flash(effect, seconds=5.0)

    def dismiss_golems(self) -> None:
        """Send away every stamp golem whose ``dismiss_on`` puzzle is solved. They free their
        tiles and leave without counting as kills."""
        gone = [
            e for e in self.enemies
            if isinstance(e, StampGolem) and e.alive
            and str(e.properties.get("dismiss_on") or "")
            and self._is_solved(str(e.properties["dismiss_on"]))
        ]
        if not gone:
            return
        for golem in gone:
            golem.dismiss(self)
            if self.locked_target is golem:
                self.locked_target = None
        self.enemies[:] = [e for e in self.enemies if e not in gone]
        self._solid_sig = None

    # ---- map-triggered dialogue ---------------------------------------------------------
    def pick_unseen(self, key: str) -> Dialogue | None:
        """First dialogue for npc key ``key`` whose requires/unless/once fit and that has not
        played yet (``seen:<id>``)."""
        flags = self._progress().flags
        return next(
            (d for d in self.dialogue_bank.for_npc(key)
             if d.eligible(flags) and d.seen_flag not in flags),
            None,
        )

    def queue_dialogue(self, key: str) -> Dialogue | None:
        """Queue the unseen dialogue for ``key`` (pushed by :meth:`update` as soon as the
        world is the top scene). It is marked seen right away so it plays once."""
        dialogue = self.pick_unseen(key)
        if dialogue is not None:
            self._progress().flags.add(dialogue.seen_flag)
            self.queued_dialogue.append(dialogue)
        return dialogue

    def _play_queued_dialogue(self) -> bool:
        if not self.queued_dialogue or self.game.scene is not self:
            return False
        self.held.clear()
        self.game.push(DialogueScene(self.game, self.queued_dialogue.pop(0)))
        return True

    def on_puzzle_skipped(self, spec: PuzzleSpec) -> None:
        """The player skipped ``spec``: Pell's ghostly bridge spans the gap (altar stays unlit)."""
        self.flash("A ghostly Pell-bridge shimmers into place. The altar stays unlit.", 5.0)

    # ---- waystones, chests, npcs ------------------------------------------------------
    def waystone_in_reach(self) -> Waystone | None:
        """The waystone whose interact box overlaps the hero, if any."""
        box = self.player.box
        return next((w for w in self.waystones if boxes_overlap(box, w.interact_box())), None)

    def use_waystone(self, waystone: Waystone) -> None:
        """Touch a waystone: it becomes the respawn point and its menu opens."""
        self.held.clear()
        key = (self.map_key, waystone.name)
        self.last_waystone = key
        self.visited_waystones.add(key)
        waystone.visited = True
        self.game.push(WaystoneMenu(self.game, self, waystone))

    def rest_at_waystone(self) -> None:
        """Waystone menu "Rest": full hearts and full ``u`` charges."""
        self.player.hp = self.player.max_hp
        self.player.refill_charges()
        self.flash("You rest. Hearts and hourglass charges restored.")

    def chest_in_reach(self) -> Chest | None:
        """The chest whose interact box overlaps the hero, if any."""
        box = self.player.box
        return next((c for c in self.chests if boxes_overlap(box, c.interact_box())), None)

    def open_chest(self, chest: Chest) -> bool:
        """Open ``chest`` once: add its coins and item. Returns False if already open."""
        loot = chest.open()
        if loot is None:
            self.flash("The chest is empty.")
            return False
        coins, item = loot
        self.player.coins += coins
        if item:
            self.player.items.append(item)
        key = getattr(chest, "obj_key", "")
        if key:
            self._progress().flags.add(f"opened:{key}")
        found = [f"{coins} coin{'s' if coins != 1 else ''}"] if coins else []
        if item:
            found.append(item)
        self.flash(f"You found {' and '.join(found)}." if found else "The chest is empty.")
        return True

    def _collect_pickups(self) -> None:
        player = self.player
        remaining: list[Pickup] = []
        for pickup in self.pickups:
            if not boxes_overlap(player.box, pickup.box):
                remaining.append(pickup)
                continue
            if pickup.kind == "potion":
                if player.hp >= player.max_hp:
                    remaining.append(pickup)
                    continue
                player.heal(pickup.amount)
            else:
                player.coins += pickup.amount
            key = getattr(pickup, "obj_key", "")
            if key:
                self._progress().flags.add(f"taken:{key}")
        self.pickups = remaining

    def npc_in_reach(self) -> Npc | None:
        """The first NPC whose interact box overlaps the player, if any."""
        box = self.player.box
        return next((n for n in self.npcs if boxes_overlap(box, n.interact_box())), None)

    def talk_to_npc_in_reach(self) -> None:
        """Open the dialogue for the NPC in reach, picking the first line set whose flags fit."""
        npc = self.npc_in_reach()
        if npc is None:
            return
        flags = self._progress().flags
        dialogue = self.dialogue_bank.pick(npc.key, flags)
        if dialogue is None:
            self.flash(f"{npc.name} has nothing to say.")
            return
        self.held.clear()
        self.game.push(DialogueScene(self.game, dialogue))

    # ---- doors and plates -------------------------------------------------------------
    def pressed_plates(self) -> set[str]:
        """Names of plates with a liftable resting on them."""
        return {p.name for p in self.plates if p.pressed}

    def _update_world_state(self) -> None:
        """Recompute plates and door locks; rebuild dynamic collision when they change."""
        for plate in self.plates:
            plate.pressed = any(plate.holds(lift) for lift in self.liftables)
        pressed = self.pressed_plates()
        progress = self._progress()
        for door in self.doors:
            door.lock_reason = door_lock_reason(door, progress.flags, self._is_solved, pressed)
            door.locked = bool(door.lock_reason)
        ts = self.tilemap.tile_size
        sig = (
            tuple(d.locked for d in self.doors),
            tuple(sorted(lift.tile(ts) for lift in self.liftables)),
        )
        if sig == self._solid_sig:
            return
        self._solid_sig = sig
        solid = list(self._base_solid)
        width = self.collision.width
        blocked: list[tuple[int, int]] = [lift.tile(ts) for lift in self.liftables]
        for enemy in self.enemies:  # a rebuild must not open a standing golem's doorway
            if isinstance(enemy, StampGolem) and enemy.alive:
                blocked.extend(enemy.blocked_tiles)
        for door in self.doors:
            if door.locked:
                blocked.extend(door.tiles(ts))
        for tx, ty in blocked:
            if not (0 <= tx < width and 0 <= ty < self.collision.height):
                continue
            if boxes_overlap(self.player.box, (tx * ts, ty * ts, ts, ts)):
                continue  # never wall the hero in
            solid[ty * width + tx] = True
        self.collision.solid = solid

    def _check_doors(self) -> None:
        box = self.player.box
        touching: Door | None = None
        exit_door: Door | None = None
        for door in self.doors:
            if door.locked:
                if boxes_overlap(box, door.touch_box()):
                    touching = door
            elif door.is_exit and boxes_overlap(box, door.box):
                exit_door = door
        if touching is not None and touching is not self._touching:
            self.flash(touching.lock_reason)
        self._touching = touching
        if not self._door_armed:
            self._door_armed = exit_door is None
            return
        if exit_door is not None:
            self.travel(exit_door.target, spawn=exit_door.spawn)

    # ---- saving -----------------------------------------------------------------------
    def world_extras(self) -> dict[str, Any]:
        """World state that is not in Progress (saved as ``progress["world"]``)."""
        p = self.player
        return {
            "coins": p.coins,
            "hearts_max": p.hearts_max,
            "u_charges": p.u_charges,
            "items": list(p.items),
            "last_waystone": list(self.last_waystone) if self.last_waystone else None,
            "marks": {k: list(v) for k, v in sorted(self.marks.items())},
            "visited_waystones": sorted(list(v) for v in self.visited_waystones),
            "unlocked": sorted(self.unlocked),
            "crates": {
                ref: {k: list(v) for k, v in sorted(by_name.items())}
                for ref, by_name in sorted(self.crates.items()) if by_name
            },
        }

    def apply_extras(self, extras: dict[str, Any] | None) -> None:
        """Inverse of :meth:`world_extras` (tolerant of missing keys)."""
        extras = extras or {}
        p = self.player
        if "hearts_max" in extras:
            p.hearts_max = int(extras["hearts_max"])
        p.coins = int(extras.get("coins", p.coins))
        p.u_charges = int(extras.get("u_charges", p.u_charges))
        p.items = [str(i) for i in extras.get("items", p.items) or []]
        last = extras.get("last_waystone")
        if isinstance(last, list | tuple) and len(last) == 2:
            self.last_waystone = (str(last[0]), str(last[1]))
        marks = extras.get("marks")
        if isinstance(marks, dict):
            self.marks = {
                str(k): (str(v[0]), str(v[1])) for k, v in marks.items()
                if isinstance(v, list | tuple) and len(v) == 2
            }
        visited = extras.get("visited_waystones")
        if isinstance(visited, list):
            self.visited_waystones = {
                (str(v[0]), str(v[1])) for v in visited if isinstance(v, list | tuple)
                and len(v) == 2
            }
            for ws in self.waystones:
                ws.visited = (self.map_key, ws.name) in self.visited_waystones
        # ``unlocked`` is saved for reference only: it is re-derived from the progress flags.
        self.refresh_unlocks(announce=False)
        crates = extras.get("crates")
        if isinstance(crates, dict):
            self.crates = {
                str(ref): {
                    str(k): [int(v[0]), int(v[1])] for k, v in by_name.items()
                    if isinstance(v, list | tuple) and len(v) == 2
                }
                for ref, by_name in crates.items() if isinstance(by_name, dict)
            }
            self._apply_crates()
            self._solid_sig = None

    def save_state(self) -> SaveState:
        """Snapshot the world and progress for the save store."""
        p = self.player
        player_state = PlayerState(p.x, p.y, p.hp, FACING_NAMES.get(p.facing, "down"))
        for attr in ("coins", "hearts_max", "u_charges"):
            if hasattr(player_state, attr):  # newer PlayerState versions carry these
                setattr(player_state, attr, getattr(p, attr))
        progress = self._progress().to_dict()
        progress["world"] = self.world_extras()
        return SaveState(
            map=self.map_key,
            player=player_state,
            progress=progress,
            area_name=self.area_name,
            waystone=self.last_waystone[1] if self.last_waystone else self.area_name,
        )

    def restore_state(self, state: SaveState) -> None:
        """Apply a loaded save: map, position, hp and world extras (Progress is the
        caller's job: ``game.progress = Progress.from_dict(state.progress)``)."""
        self.refresh_unlocks(announce=False)  # a restored save does not re-announce stances
        if state.map:
            path = resolve_map(state.map)
            if path.exists():
                if path.resolve() != self.map_path.resolve():
                    self.load_map(path)
                self.player.x, self.player.y = state.player.x, state.player.y
                self.player.facing = NAMED_FACINGS.get(state.player.facing, (0, 1))
        extras = state.progress.get("world") if isinstance(state.progress, dict) else None
        self.apply_extras(extras if isinstance(extras, dict) else None)
        for attr in ("coins", "hearts_max", "u_charges"):
            value = getattr(state.player, attr, None)
            if value is not None:
                setattr(self.player, attr, int(value))
        self.player.hp = max(1, min(self.player.max_hp, state.player.hp))
        self.player.trail.clear()
        self.camera.follow(*self.player.center)
        self._solid_sig = None
        self.refresh_unlocks(announce=False)
        self._update_world_state()
        self._sync_altars()

    def save_game(self) -> None:
        """``:save``: write the slot and seal it in the Ledger (a git commit) when enabled."""
        receipt = self._seal()
        if receipt is None:
            self.flash("No save store.")
            return
        self._progress().flags.add("first_seal")
        if receipt.sha:
            self.flash(f"Sealed in the Ledger.  git commit -> {receipt.sha}", 4.0)
        else:
            self.flash("Saved.", 3.0)

    def _seal(self, message: str | None = None) -> SaveReceipt | None:
        """Write the slot (and commit it to the Ledger when git is on); no flash."""
        saves = getattr(self.game, "saves", None)
        if saves is None:
            return None
        receipt: SaveReceipt = saves.save(SAVE_SLOT, self.save_state(), message)
        return receipt

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

    # ---- death ------------------------------------------------------------------------
    def respawn(self) -> None:
        """The hero fell: wake at the last waystone (or the map spawn) with full hearts."""
        p = self.player
        p.hp = p.max_hp
        p.dash_time = p.knockback_time = 0.0
        p.carrying = None
        p.rewind_path = []
        self.exit_visual()
        self.held.clear()
        if self.last_waystone is not None:
            ref, name = self.last_waystone
            self._arrive(ref, None, name)
            self.flash(f"You wake at {name}.")
        else:
            p.place_center(*self.spawn_point)
            self.flash("You wake at the spawn point.")
        p.iframes = HURT_IFRAMES

    # ---- guidance ---------------------------------------------------------------------
    def _show_controls_hint(self) -> bool:
        """Show the one-line key hint until the player has left Little Tilde."""
        flags = self._progress().flags
        return "entered:echo_vale" not in flags and not self.show_help

    def objective_targets(self) -> list[Entity]:
        """Things worth walking to right now: NPCs with an unplayed line for the current
        flags, unlit altars, and unopened chests. Drawn with a bouncing arrow."""
        targets: list[Entity] = []
        for npc in self.npcs:
            if self.pick_unseen(npc.key) is not None:
                targets.append(npc)
        targets.extend(a for a in self.altars if not a.lit)
        targets.extend(c for c in self.chests if not c.opened)
        return targets

    def _draw_markers(self, view: pygame.Surface, offset: tuple[int, int]) -> None:
        """Bouncing arrows above objective targets, and a key badge on the thing in reach."""
        bounce = -int(abs(math.sin(self.time * 4.0)) * 3)
        for ent in self.objective_targets():
            cx = round(ent.x + ent.w / 2) - offset[0]
            top = round(ent.y) - offset[1] - 6 + bounce
            pts = [(cx - 3, top - 4), (cx + 3, top - 4), (cx, top)]
            pygame.draw.polygon(view, MARKER_COLOR, pts)
            pygame.draw.polygon(view, (20, 20, 24), pts, 1)
        near = self.npc_in_reach() or self.altar_in_reach() or self.chest_in_reach()
        if near is None:
            near = self.waystone_in_reach()
        if near is not None:
            cx = round(near.x + near.w / 2) - offset[0]
            top = round(near.y) - offset[1] - 15
            badge = pygame.Rect(cx - 4, top, 9, 9)
            pygame.draw.rect(view, (20, 20, 24), badge)
            pygame.draw.rect(view, MARKER_COLOR, badge, 1)
            pygame.draw.line(view, MARKER_COLOR, (cx, top + 3), (cx, top + 6))
            view.set_at((cx, top + 1), MARKER_COLOR)

    #: Rows of the ``?`` overlay: (keys, what it does, gating mechanic or None).
    HELP_ROWS: tuple[tuple[str, str, str | None], ...] = (
        ("h j k l", "walk (hold)", None),
        ("x", "strike a bug", None),
        ("i  or  Enter", "talk, read, use an altar, open a chest", None),
        ("w / b / e", "dash forward / back / short hop", "dash"),
        ("3j  3x", "count first: dash 3 tiles, strike 3 times", "counts"),
        ("v", "VISUAL: lock on to a bug, h j k l to cycle", "visual"),
        ("dd", "cleave the whole row you face", "cleave"),
        ("u", "rewind 3 s (3 charges, refilled at waystones)", "rewind"),
        ("yy / p", "lift a crate / put it down", "yank"),
        ("/word  then  n", "search for things by name, next match", "search"),
        ("ma  /  'a", "set a mark at a waystone / jump back to it", "marks"),
        (":save  :ledger", "seal a save in git / read the Ledger", None),
        ("Esc", "when in doubt, Escape", None),
    )

    def _draw_help(self, surface: pygame.Surface) -> None:
        """The controls overlay toggled with ``?`` or F1. Mechanics not yet learned are
        dimmed, with a padlock and "(not yet learned)"."""
        w, h = surface.get_size()
        rows = self.HELP_ROWS
        panel_h = 60 + 26 * len(rows)
        panel = pygame.Rect(w // 2 - 450, h // 2 - panel_h // 2, 900, panel_h)
        shade = pygame.Surface((w, h), pygame.SRCALPHA)
        shade.fill((0, 0, 0, 150))
        surface.blit(shade, (0, 0))
        pygame.draw.rect(surface, (14, 13, 18), panel)
        pygame.draw.rect(surface, MARKER_COLOR, panel, 2)
        draw_text(
            surface, "The Four Stances   (press ? or Esc to close)",
            (panel.x + 18, panel.y + 12), size=18, color=MARKER_COLOR,
        )
        y = panel.y + 48
        for key, what, mechanic in rows:
            locked = mechanic is not None and mechanic not in self.unlocked
            key_color = theme.DIM if locked else (230, 225, 210)
            what_color = theme.DIM if locked else (170, 165, 155)
            if locked:
                draw_lock_glyph(surface, (panel.x + 8, y + 3), theme.DIM)
                what = f"{what}  (not yet learned)"
            draw_text(surface, key, (panel.x + 24, y), size=16, color=key_color)
            draw_text(surface, what, (panel.x + 210, y), size=16, color=what_color)
            y += 26

    # ---- simulation -------------------------------------------------------------------
    def update(self, dt: float) -> None:
        """One fixed step: player, enemies, combat, items, doors, camera."""
        self.time += dt
        if self.message_time > 0:
            self.message_time -= dt
        self.refresh_unlocks()
        self._update_toast(dt)
        self.area_card.update(dt)
        if self.companion is not None:
            self.companion.update(dt, self.player)
        if self.fade.active:
            self.fade.update(dt)
            self.camera.follow(*self.player.center)
            return
        if self._play_queued_dialogue():
            return
        player = self.player
        typing = self.search_input is not None
        move = self.move_vector() if self.modes.mode is Mode.NORMAL and not typing else (0, 0)
        player.update(dt, self, move=move)
        for ent in (*self.altars, *self.waystones, *self.pickups):
            ent.update(dt, self)
        combat.update_enemies(self, dt)
        box = player.attack_box()
        if box is not None:
            combat.resolve_player_attacks(self, box, 1, "strike", struck=player.struck)
        combat.reap(self)
        self._collect_pickups()
        self._update_world_state()
        self._check_doors()
        self._check_lock()
        if player.hp <= 0:
            self.respawn()
        self.focus_time = max(0.0, self.focus_time - dt)
        focus = self.focus if self.focus_time > 0 and self.focus is not None else player
        self.camera.follow(*focus.center)

    # ---- rendering --------------------------------------------------------------------
    def draw(self, surface: pygame.Surface) -> None:
        """Render the world at 1x into the view, scale 3x nearest-neighbour, then overlay text."""
        view = self.view
        view.fill(BG_COLOR)
        offset = self.camera.offset
        self.tilemap.draw_below(view, offset)
        entities: list[Entity] = [*self.all_entities(), self.player]
        if self.companion is not None:
            entities.append(self.companion)
        for ent in sorted(entities, key=lambda e: e.bottom):
            ent.draw(view, offset)
        self.tilemap.draw_above(view, offset)
        self._draw_search(view, offset)
        self._draw_lock(view, offset)
        self._draw_markers(view, offset)
        pygame.transform.scale(view, surface.get_size(), surface)
        self._draw_overlay(surface)
        if self.show_help:
            self._draw_help(surface)

    @staticmethod
    def _sprite_rect(ent: Entity, offset: tuple[int, int]) -> pygame.Rect:
        x = round(ent.x + ent.w / 2 - 8) - offset[0]
        y = round(ent.y + ent.h - 16) - offset[1]
        return pygame.Rect(x, y, 16, 16)

    def _draw_search(self, view: pygame.Surface, offset: tuple[int, int]) -> None:
        current = self.current_match
        for ent in self.search_matches:
            if not ent.alive:
                continue
            rect = self._sprite_rect(ent, offset).inflate(2, 2)
            pygame.draw.rect(view, SEARCH_COLOR, rect, 2 if ent is current else 1)
        if current is not None and current.alive:
            px, py = self.player.center
            tx, ty = current.center
            angle = math.atan2(ty - py, tx - px)
            cx = px - offset[0] + math.cos(angle) * 14
            cy = py - offset[1] + math.sin(angle) * 14
            tip = (cx + math.cos(angle) * 4, cy + math.sin(angle) * 4)
            left = (cx + math.cos(angle + 2.5) * 4, cy + math.sin(angle + 2.5) * 4)
            right = (cx + math.cos(angle - 2.5) * 4, cy + math.sin(angle - 2.5) * 4)
            pygame.draw.polygon(view, SEARCH_COLOR, [tip, left, right])

    def _draw_lock(self, view: pygame.Surface, offset: tuple[int, int]) -> None:
        target = self.locked_target
        if target is None or not target.alive:
            return
        r = self._sprite_rect(target, offset).inflate(6, 6)
        n = 4
        for (x, y), (dx, dy) in (
            (r.topleft, (1, 1)), (r.topright, (-1, 1)),
            (r.bottomleft, (1, -1)), (r.bottomright, (-1, -1)),
        ):
            x -= 1 if dx < 0 else 0
            y -= 1 if dy < 0 else 0
            pygame.draw.line(view, VISUAL_COLOR, (x, y), (x + dx * n, y))
            pygame.draw.line(view, VISUAL_COLOR, (x, y), (x, y + dy * n))

    def _prompt(self) -> str:
        npc = self.npc_in_reach()
        if npc is not None and self.altar_in_reach() is None:
            label = npc.name if npc.name and not npc.name.startswith("#") else "it"
            verb = "look at" if npc.key in ("ink_shelf", "namestone_sign") else "talk to"
            return f"i / Enter: {verb} {label}"
        if self.altar_in_reach() is not None:
            return "i / Enter: use altar"
        if self.waystone_in_reach() is not None:
            return "i / Enter: use waystone"
        chest = self.chest_in_reach()
        if chest is not None and not chest.opened:
            return "i / Enter: open chest"
        if self.player.carrying is None and self.liftable_in_reach() is not None:
            return "yy: lift"
        return ""

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
        pending = self.pending_key or (self._pending_op[0] if self._pending_op else "")
        if pending:
            showcmd = render_text(pending, 16)
            draw_text(surface, pending, (w - showcmd.get_width() - 12, h - 24), size=16)
        self.area_card.draw(surface)
        if self.toast:
            draw_toast(surface, self.toast)
        if self._show_controls_hint():
            hint = "h j k l  walk     x  strike     i / Enter  talk & use     ?  help"
            hw = render_text(hint, 14).get_width()
            draw_text(surface, hint, (w - hw - 8, h - 46), size=14, color=(200, 190, 170))
        if self.modes.mode is Mode.COMMAND:
            pygame.draw.rect(surface, (0, 0, 0), (0, h - 26, w, 26))
            draw_text(surface, ":" + self.modes.command_buffer + "_", (8, h - 22), size=16)
        elif self.search_input is not None:
            pygame.draw.rect(surface, (0, 0, 0), (0, h - 26, w, 26))
            draw_text(surface, "/" + self.search_input + "_", (8, h - 22), size=16)
        elif self.message_time > 0 and self.message:
            draw_text(surface, self.message, (8, h - 24), size=16)
        else:
            prompt = self._prompt()
            if prompt:
                draw_text(surface, prompt, (8, h - 24), size=16, color=(160, 240, 200))
        self.fade.draw(surface)
