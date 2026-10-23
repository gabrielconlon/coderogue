"""CodeRogue entry point. The real loop lands in Phase 1; this boots a window and exits."""

from __future__ import annotations

import sys


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    import pygame

    pygame.init()
    print(f"CodeRogue bootstrap. pygame-ce {pygame.version.ver}")
    pygame.quit()
    return 0
