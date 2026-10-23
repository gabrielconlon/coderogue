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
`subprocess` with `start_new_session=True` and `os.killpg` when the script ends (exit,
timeout or output cap alike), a fresh temp dir as cwd, a scrubbed env (`PATH`, `HOME=$TMP`,
`LANG=C.UTF-8`, plus a per-run `CODEROGUE_RUN` tag), stdout/stderr caps. Python runs as
`python -I -S -B main.py`. On POSIX a small launcher sets `RLIMIT_CPU` (ceil(timeout +
start-up allowance) + 1, so the wall clock fires first; a SIGXCPU death still reads as a
timeout), `RLIMIT_FSIZE`, `RLIMIT_NOFILE` (64; 256 for PowerShell) and, on Linux only,
`RLIMIT_NPROC`, then execs. Linux counts `RLIMIT_NPROC` in threads across all of the user's
processes, so the cap is the user's current thread count + 256 with a floor of 1024: it only
stops a runaway fork loop, and the wall-clock kill remains the real backstop. Processes that
escape the group with `setsid` and keep the output pipes open are found by the run tag
(Linux) or a cwd inside the temp dir (Linux, macOS) and killed; pipes whose reader is still
blocked are never closed. On Windows the child runs in a kill-on-close Job Object
(`taskkill /T /F` if one cannot be made). Not a security boundary; documented in README.

## Adding a language
Add `coderogue/languages/<name>.py` implementing the `Language` protocol in
`languages/__init__.py`, register it, and add a `<name>:` block under `languages` in each
puzzle YAML. The validator only looks at stdout, files, and exit codes.
