# CodeRogue

A top-down, real-time action roguelike in the spirit of Zelda that teaches programming.
You walk and fight with VIM keys. You solve the kingdom's problems by writing real
Python, bash, or PowerShell at ancient altars. Open source (MIT), built with Python and
Pygame-CE on Kenney's CC0 pixel art.

**Status:** pre-alpha, MVP in progress. See `docs/DESIGN.md` for the design bible.

## Run from source

```sh
python3 -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
python tools/fetch_assets.py        # downloads Kenney packs (CC0) into assets/kenney/
python -m coderogue
```

Requires Python 3.12 or newer. Puzzles in Python run with the same interpreter during
development. bash puzzles need bash on macOS or Linux (Homebrew bash is preferred on macOS).
PowerShell puzzles need `pwsh` or Windows PowerShell.

## Keys

| Key | World | Editor |
|---|---|---|
| `h j k l` | walk | move cursor |
| `x` | strike a bug | delete a character |
| `w b e` | dash | jump by word |
| `i` | write at an altar | insert mode |
| `Esc` | back to NORMAL, always | back to NORMAL, always |
| `:w` `:q` | cast, leave | cast, leave |

Arrow keys and WASD can be enabled in settings.

## Tests

```sh
pytest
python tools/validate_content.py    # runs every puzzle's reference solution
```

## Player code and safety

Player code runs as a local subprocess with a timeout, a fresh temporary directory, a
scrubbed environment, and output limits. On Linux and macOS it also gets CPU, file-size,
and process-count limits where the OS allows. This protects against accidents such as
infinite loops. It is **not** a security boundary: the code runs as you, on your machine,
the same as running a script you wrote yourself.

## License

MIT. Art and audio by Kenney (CC0). Fonts: see `CREDITS.md`.
