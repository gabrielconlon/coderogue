"""The altar editor: a pure-Python buffer and VIM state machine plus a pygame view.

``buffer`` and ``vim`` never import pygame; ``render`` and ``keys`` do, so import them
explicitly (``from coderogue.editor.render import EditorView``).
"""

from coderogue.editor.buffer import Buffer
from coderogue.editor.vim import Mode, Register, VimEditor

__all__ = ["Buffer", "Mode", "Register", "VimEditor"]
