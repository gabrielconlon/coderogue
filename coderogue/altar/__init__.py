"""The altar: the modal puzzle editor scene and puzzle lookup helpers.

Usage from the world::

    from coderogue.altar import AltarScene, game_puzzles, resolve_puzzle_id

    puzzles = game_puzzles(game)                 # cached on game.puzzles
    pid = resolve_puzzle_id(puzzles, altar.puzzle)
    game.push(AltarScene(game, world, altar, puzzles[pid], game.progress))
"""

from coderogue.altar.lookup import game_puzzles, resolve_puzzle_id
from coderogue.altar.scene import AltarScene

__all__ = ["AltarScene", "game_puzzles", "resolve_puzzle_id"]
