# Architecture (MVP)

Single package `coderogue/` with a fixed-timestep loop (60 Hz update, render each frame),
a scene stack, and an input layer that is a VIM mode machine (NORMAL / INSERT / VISUAL /
COMMAND). Content is data under `content/` (Tiled `.tmj` maps, YAML puzzles and dialogue).

```
SDL events -> input/modes.py (mode machine) -> actions
Scenes: Title -> World (real-time) <-> Altar (editor modal, time frozen) / Dialogue / Pause
World:  world/loader.py (.tmj) -> TileMap + collision grid + entity spawns + triggers
Puzzle: puzzles/spec.py (YAML) -> editor buffer -> puzzles/runner.py (subprocess) -> validate -> reward
Save:   save/store.py (JSON) + save/gitstore.py (optional git commit/tag)
```

| Module | Responsibility |
|---|---|
| `app.py` | main loop, clock, scene stack, `resource_path()` |
| `input/modes.py`, `input/keymap.py` | mode machine; default VIM map; arrows/WASD fallback toggle |
| `world/` | tilemap, camera, collision, Tiled loader |
| `entities/` | player, enemies, items, altar, npc; `combat.py` hitboxes, i-frames, knockback |
| `editor/` | `buffer.py` text buffer, `vim.py` motions and operators, `render.py` |
| `puzzles/` | spec loader, runner, validators, `sandbox_posix.py`, `sandbox_win.py` |
| `languages/` | registry; one module per language (detect, command, highlight tokens, error catalogue) |
| `story/` | dialogue, quests, flags |
| `save/` | JSON store and git layer with graceful fallback |
| `ui/` | HUD, panels, text |

## Player code sandbox
`subprocess` with `start_new_session=True` and `os.killpg` on timeout, a fresh temp dir as
cwd, a scrubbed env (`PATH`, `HOME=$TMP`, `LANG=C.UTF-8`), stdout/stderr caps. Python runs
as `python -I -S -B main.py`. On POSIX a small launcher sets `RLIMIT_CPU`, `RLIMIT_FSIZE`,
`RLIMIT_NOFILE`, `RLIMIT_NPROC` then execs. Not a security boundary; documented in README.

## Adding a language
Add `coderogue/languages/<name>.py` implementing the `Language` protocol in
`languages/__init__.py`, register it, and add a `<name>:` block under `languages` in each
puzzle YAML. The validator only looks at stdout, files, and exit codes.
