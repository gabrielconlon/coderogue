# Contributing

- Python 3.12+. `pip install -e ".[dev]"`, then `python tools/fetch_assets.py`.
- `ruff check .` and `pytest` must pass. CI runs on macOS, Linux, and Windows.
- Content (maps, puzzles, dialogue) lives in `content/` and needs no engine changes.
  Run `python tools/validate_content.py` after editing puzzles: every reference solution
  must pass its tests and every starter must fail them.
- Never commit `assets/kenney/`; it is fetched. Fonts under `assets/fonts/` are committed
  with their licenses.
- Keep pull requests to one phase or one chapter of content.
