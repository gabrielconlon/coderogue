"""CodeRogue entry point: game loop, scene stack, window scaling and ``resource_path``."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from coderogue.puzzles import PuzzleSpec
    from coderogue.scene import Scene
    from coderogue.world.scene import WorldScene

LOGICAL_SIZE = (960, 540)
UPDATE_HZ = 60
FIXED_DT = 1.0 / UPDATE_HZ
MAX_FRAME_TIME = 0.25  # clamp after stalls (window drag, breakpoint) to avoid a spiral
MAX_STEPS_PER_FRAME = 5
DEFAULT_MAP = ("content", "maps", "little_tilde_scriptorium.tmj")
TITLE = "CodeRogue"

REPO_ROOT = Path(__file__).resolve().parent.parent


def resource_path(*parts: str) -> Path:
    """Absolute path to a bundled resource (repo root, or ``sys._MEIPASS`` when frozen)."""
    base = getattr(sys, "_MEIPASS", None)
    root = Path(base) if base else REPO_ROOT
    return root.joinpath(*parts)


def letterbox_rect(window: tuple[int, int], logical: tuple[int, int]) -> tuple[int, int, int, int]:
    """Where to draw ``logical`` inside ``window``: integer scale if it fits, else best fit.

    Returns (x, y, w, h), centred.
    """
    ww, wh = window
    lw, lh = logical
    iscale = min(ww // lw, wh // lh)
    if iscale >= 1:
        w, h = lw * iscale, lh * iscale
    else:
        s = min(ww / lw, wh / lh)
        w, h = max(1, int(lw * s)), max(1, int(lh * s))
    return ((ww - w) // 2, (wh - h) // 2, w, h)


class Game:
    """Owns the window, the clock and the scene stack, and runs the fixed-timestep loop.

    Updates run at exactly ``UPDATE_HZ`` using an accumulator; rendering happens once per
    loop iteration. Scenes draw on ``self.surface`` (960x540), which is scaled to the window
    with nearest-neighbour and letterboxed.
    """

    def __init__(self, headless: bool = False, title: str = TITLE) -> None:
        import pygame

        self.headless = headless
        pygame.init()
        pygame.display.set_caption(title)
        flags = 0 if headless else pygame.RESIZABLE
        self.window = pygame.display.set_mode(LOGICAL_SIZE, flags)
        self.surface = pygame.Surface(LOGICAL_SIZE).convert()
        self.clock = pygame.time.Clock()
        self.scenes: list[Scene] = []
        self.running = False
        self.frame = 0
        self.time = 0.0  # simulated seconds
        self.arrows_fallback = False
        from coderogue.progress import Progress

        self.puzzles: dict[str, PuzzleSpec] = {}  # loaded lazily by coderogue.altar
        self.progress = Progress()
        from coderogue.save.store import SaveStore

        self.saves = SaveStore()
        self.world: WorldScene | None = None  # the one world scene, once play starts

    # ---- scene stack ------------------------------------------------------------------
    @property
    def scene(self) -> Scene | None:
        """The top scene, or None if the stack is empty."""
        return self.scenes[-1] if self.scenes else None

    def push(self, scene: Scene) -> None:
        """Push ``scene`` on top; it gets events and updates until popped."""
        self.scenes.append(scene)
        scene.on_enter()

    def pop(self) -> Scene | None:
        """Pop the top scene. The game stops when the stack becomes empty."""
        if not self.scenes:
            return None
        scene = self.scenes.pop()
        scene.on_exit()
        if self.scenes:
            self.scenes[-1].on_resume()
        else:
            self.running = False
        return scene

    def replace(self, scene: Scene) -> None:
        """Swap the top scene for ``scene``."""
        if self.scenes:
            self.scenes.pop().on_exit()
        self.push(scene)

    def quit(self) -> None:
        """Stop the loop at the end of the current frame."""
        self.running = False

    # ---- loop -------------------------------------------------------------------------
    def step(self, dt: float = FIXED_DT) -> None:
        """Run one fixed update on the top scene."""
        if self.scene is not None:
            self.scene.update(dt)
        self.time += dt

    def draw(self) -> None:
        """Draw visible scenes to the logical surface and present it."""
        import pygame

        self.surface.fill((0, 0, 0))
        start = len(self.scenes) - 1
        while start > 0 and self.scenes[start].transparent:
            start -= 1
        for scene in self.scenes[max(start, 0) :]:
            scene.draw(self.surface)
        self.present()
        pygame.display.flip()

    def present(self) -> None:
        """Scale the logical surface into the window (nearest-neighbour, letterboxed)."""
        import pygame

        win = pygame.display.get_surface()
        if win is None:
            return
        size = win.get_size()
        if size == LOGICAL_SIZE:
            win.blit(self.surface, (0, 0))
            return
        x, y, w, h = letterbox_rect(size, LOGICAL_SIZE)
        win.fill((0, 0, 0))
        win.blit(pygame.transform.scale(self.surface, (w, h)), (x, y))

    def window_to_logical(self, pos: tuple[int, int]) -> tuple[int, int]:
        """Map a window pixel (mouse) to logical coordinates."""
        import pygame

        win = pygame.display.get_surface()
        size = win.get_size() if win else LOGICAL_SIZE
        x, y, w, h = letterbox_rect(size, LOGICAL_SIZE)
        return ((pos[0] - x) * LOGICAL_SIZE[0] // w, (pos[1] - y) * LOGICAL_SIZE[1] // h)

    def run(self, max_frames: int | None = None) -> int:
        """Run until quit (or ``max_frames`` rendered frames). Returns an exit code."""
        import pygame

        self.running = True
        accumulator = 0.0
        self.clock.tick()
        while self.running and self.scenes:
            if self.headless:
                self.clock.tick()
                frame_time = FIXED_DT  # deterministic and as fast as possible
            else:
                frame_time = min(self.clock.tick(UPDATE_HZ) / 1000.0, MAX_FRAME_TIME)
            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    self.running = False
                elif self.scene is not None:
                    self.scene.handle_event(event)
            accumulator += frame_time
            steps = 0
            while accumulator >= FIXED_DT - 1e-9 and steps < MAX_STEPS_PER_FRAME:
                self.step(FIXED_DT)
                accumulator -= FIXED_DT
                steps += 1
            if steps == MAX_STEPS_PER_FRAME:
                accumulator = 0.0
            if not self.scenes:
                break
            self.draw()
            self.frame += 1
            if max_frames is not None and self.frame >= max_frames:
                break
        return 0


def _resolve_map(path: str | None) -> Path:
    if path is None:
        return resource_path(*DEFAULT_MAP)
    p = Path(path)
    if p.exists():
        return p.resolve()
    return resource_path(path)


def build_parser() -> argparse.ArgumentParser:
    """Command-line arguments for ``python -m coderogue``."""
    parser = argparse.ArgumentParser(prog="coderogue", description="CodeRogue")
    parser.add_argument(
        "--headless-frames",
        type=int,
        metavar="N",
        help="run N frames with the dummy video driver and exit (smoke tests)",
    )
    parser.add_argument("--map", metavar="PATH", help="Tiled .tmj map to load")
    parser.add_argument(
        "--arrows", action="store_true", help="also bind arrow keys and WASD (fallback)"
    )
    parser.add_argument("--new", action="store_true", help="ignore the saved slot; start fresh")
    # Hidden: support/packaging check. Prints languages, content and asset status, then exits.
    parser.add_argument("--doctor", action="store_true", help=argparse.SUPPRESS)
    return parser


#: Files whose absence means a broken install (checked by ``--doctor``).
DOCTOR_CHECKS: tuple[tuple[str, ...], ...] = (
    DEFAULT_MAP,
    ("content", "quests.yaml"),
    ("content", "puzzles"),
    ("content", "dialogue"),
    ("assets", "fonts"),
    ("assets", "kenney", "tiny-dungeon", "Tilemap", "tilemap_packed.png"),
    ("assets", "kenney", "tiny-town", "Tilemap", "tilemap_packed.png"),
)


#: One-line programs ``--doctor`` runs through the real sandbox for each language found.
DOCTOR_HELLO = {"python": 'print("hello")', "bash": "echo hello", "powershell": "'hello'"}


def doctor() -> int:
    """Print what this install can see and run a one-liner in each language found.

    Exit code 1 if required content or assets are missing, or a found Python cannot run.
    """
    from coderogue.languages import registry
    from coderogue.puzzles.sandbox import run_script

    frozen = bool(getattr(sys, "frozen", False))
    print(f"CodeRogue doctor (frozen={frozen}, python={sys.version.split()[0]})")
    print(f"resource root: {resource_path()}")
    print(f"content dir:   {resource_path('content')}")
    ok = True
    for parts in DOCTOR_CHECKS:
        p = resource_path(*parts)
        present = p.exists()
        ok = ok and present
        print(f"  [{'ok' if present else 'MISSING'}] {'/'.join(parts)}")
    maps = sorted(resource_path("content", "maps").glob("*.tmj"))
    print(f"  maps: {len(maps)}")
    print("languages:")
    for lid, lang in registry().items():
        rt = lang.detect()
        if rt is None:
            print(f"  {lid}: not found (greyed out)")
            continue
        res = run_script(lang, rt, DOCTOR_HELLO.get(lid, ""), timeout_s=10.0)
        ran = res.stdout.strip() == "hello"
        if lid == "python":  # the one we ship; bash/pwsh are the player's own installs
            ok = ok and ran
        status = "runs ok" if ran else f"FAILED to run: {(res.stderr or res.stdout).strip()[:200]}"
        print(f"  {lid}: {rt.version_str} at {rt.executable} ({status})")
    return 0 if ok else 1


def _restore_save(game: Game, world: WorldScene) -> None:
    """Load slot1 (progress, map, position, coins, waystones...) if it exists."""
    from coderogue.progress import Progress
    from coderogue.world.scene import SAVE_SLOT

    try:
        state = game.saves.load(SAVE_SLOT)
    except Exception:  # noqa: BLE001 - a corrupt save must never block starting the game
        return
    if state is None:
        return
    game.progress = Progress.from_dict(state.progress)
    try:
        world.restore_state(state)
    except Exception:  # noqa: BLE001 - a save pointing at a broken map must not block play
        world._sync_altars()


def start_world(game: Game, map_path: Path, new: bool = False) -> WorldScene:
    """Build the world scene (restoring slot1 unless ``new``) and remember it as
    ``game.world``."""
    from coderogue.progress import Progress
    from coderogue.world.scene import WorldScene

    if new:
        game.progress = Progress()
    world = WorldScene(game, map_path)
    if not new:
        _restore_save(game, world)
    game.world = world
    return world


def main(argv: list[str] | None = None) -> int:
    """Entry point. Returns a process exit code."""
    args = build_parser().parse_args(sys.argv[1:] if argv is None else argv)
    if args.doctor:
        return doctor()
    headless = args.headless_frames is not None
    if headless:
        os.environ["SDL_VIDEODRIVER"] = "dummy"
        os.environ["SDL_AUDIODRIVER"] = "dummy"
    import pygame

    map_path = _resolve_map(args.map)
    game = Game(headless=headless)
    game.arrows_fallback = args.arrows
    try:
        if args.map is not None or headless:
            game.push(start_world(game, map_path, new=args.new))
        else:
            from coderogue.title import TitleScene

            def begin(new: bool) -> None:
                game.replace(start_world(game, map_path, new=new))

            game.push(TitleScene(game, begin))
        return game.run(max_frames=args.headless_frames if headless else None)
    finally:
        pygame.quit()


if __name__ == "__main__":
    raise SystemExit(main())
