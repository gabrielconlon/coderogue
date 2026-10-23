# CodeRogue

**A top-down action adventure that teaches you to code. Walk with VIM keys. Cast spells in Python, bash, or PowerShell.**

![CodeRogue title screen](docs/screenshots/title.png)

The kingdom of Shellmarch is written in the Source, and a grey corruption called the Null is emptying it line by line. Signs go blank, bells forget how to count, and your teacher Pell has been reduced to a single word: `None`. You are Wren, an apprentice copyist with the home row under your fingers and a reformed bug named Moth on your shoulder. Walk to the Terminal, and write the world back.

Every key you learn for the world also works in the editor. `x` kills a bug and deletes a character. `dd` cleaves a row of enemies and deletes a line. The altars where you write spells are real code, run by a real interpreter, and your output appears in the world: on the signpost, from the bell, in the ferryman's mouth.

## What it looks like

| | |
|---|---|
| ![Waking in the scriptorium](docs/screenshots/wakeup.png) | ![Little Tilde village](docs/screenshots/village.png) |
| *Wake up, learn `h j k l`, and go find the ink.* | *Bouncing arrows show where to go. Moth follows.* |
| ![Writing a spell at an altar](docs/screenshots/altar.png) | ![The altar lights](docs/screenshots/altar-solved.png) |
| *Press `i` at an altar: the world freezes and a modal editor opens. Pick Python, bash, or PowerShell per puzzle.* | *Cast with `:w`. Pass, and the altar lights. Fail, and you get a precise diff and a kind translation of the error.* |
| ![Echo Vale](docs/screenshots/echo-vale.png) | ![Grubble, the Typo King](docs/screenshots/grubble.png) |
| *Echo Vale, where the Null has eaten every name.* | *Chapter bosses are fights and coding challenges at once.* |

![Controls overlay](docs/screenshots/help.png)

## What you learn

CodeRogue follows the order of an intro programming course, with a story wrapped around it.

| Chapter | Where | Concepts | New keys |
|---|---|---|---|
| Prologue | Little Tilde | printing, sequencing, reading an error | `h j k l` `x` `i` `Esc` `:w` `:q` `:save` |
| 1 | Echo Vale | variables, arithmetic, input, strings, formatting | `w b e` `A o 0 $` |
| 2 | Branchwood and the Looping Mire | if/else, while, for, lists, filtering input | `v` counts `dd` `u` |
| 3 | The Grand Directory | dictionaries, functions, reading and writing files, pipelines | `yy p` `/ n` marks |

Every puzzle has a Python variant, a bash variant, and a PowerShell variant that teach the same idea, so you can mix and match or solve one twice for a Bilingual star. Hints come in three rungs, coding is never timed, and you can always skip and come back.

Saving is a git commit. Stand at a waystone (the signposts) and set a seal, and the game commits your progress and your spells into a local repository it calls the Ledger. By Chapter 2 you are reading `git log`, `git diff`, and `git checkout` to undo what the Null did.

## Install and run

You need **Python 3.12 or newer** and **git** (for the Ledger; the game works without it, with plain saves).

```sh
git clone https://github.com/gabrielconlon/coderogue.git
cd coderogue
python3 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
python tools/fetch_assets.py       # downloads Kenney's CC0 art packs (about 7 MB)
python -m coderogue
```

Useful flags:

```sh
python -m coderogue --new          # ignore the saved game and start over
python -m coderogue --arrows       # also bind arrow keys and WASD
python -m coderogue --doctor       # report which languages and assets were found
```

Languages are detected on your machine:

| Language | macOS | Linux | Windows |
|---|---|---|---|
| Python | yes | yes | yes |
| bash | yes (Homebrew bash preferred; stock 3.2 works through Chapter 2) | yes | with Git Bash |
| PowerShell | with `pwsh` | with `pwsh` | yes |

A puzzle only offers the variants your machine can run.

### Packaged builds

`python tools/build.py` produces a self-contained app in `dist/` with PyInstaller, including a bundled Python for player code. See [docs/PACKAGING.md](docs/PACKAGING.md). Prebuilt downloads will appear on the Releases page once the release workflow has run.

## Controls

Press `?` in the game at any time for the full list. Stances unlock as the story teaches them.

| Key | In the world | In the editor |
|---|---|---|
| `h j k l` | walk (hold) | move the cursor |
| `x` | strike a bug | delete a character |
| `i` or `Enter` | talk, read, use an altar, open a chest | insert mode |
| `w` `b` `e` | dash forward, back, short hop | jump by word |
| `v` | lock on to a bug | select text |
| `dd` | cleave the whole row you face | delete a line |
| `u` | rewind three seconds | undo |
| `yy` `p` | lift a crate, put it down | yank and put a line |
| `/word` then `n` | search for things by name | search |
| `:save` | save the game anywhere (waystones also save, rest, and open the Ledger) | |
| `:w` `:q` | | cast the spell, leave the altar |
| `Esc` | when in doubt, Escape | back to NORMAL |

## Player code and safety

Your code runs as a local subprocess with a timeout, a fresh temporary directory, a scrubbed environment, and output limits. On Linux and macOS it also gets CPU, file-size, and process limits where the OS allows. This protects against accidents such as infinite loops. It is **not** a security boundary: the code runs as you, on your machine, the same as running a script you wrote yourself.

## Contributing

Content lives in `content/` and needs no engine changes: puzzles are YAML, maps are generated from readable ASCII sources with `python tools/mapgen.py`, dialogue is YAML. Adding a language is one plugin module plus puzzle variants. See [docs/CONTRIBUTING.md](docs/CONTRIBUTING.md), [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md), and the design bible in [docs/DESIGN.md](docs/DESIGN.md).

```sh
pytest                              # the test suite, headless
python tools/validate_content.py    # runs every puzzle's reference solution
```

## License and credits

Code is MIT. Art and audio are by [Kenney](https://kenney.nl) (CC0). The editor font is JetBrains Mono (OFL). See [CREDITS.md](CREDITS.md).
