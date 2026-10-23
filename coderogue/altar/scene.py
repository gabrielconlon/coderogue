"""The altar: a modal editor scene pushed over the frozen world.

Layout on the 960x540 logical surface::

    +--------------------------------------------------------------+
    | Title                            [python]  bash  powershell  |  lore strip
    | lore text, word-wrapped ...                                  |
    +--------------------------------------------------------------+
    |  1 print("Hello, Tilde.")                                    |  EditorView
    |  ...                                                -- INSERT |
    +--------------------------------------------------------------+
    | Moth's hint bubble / failing test + diff / error / success   |  result pane
    +--------------------------------------------------------------+

Keys go through :class:`~coderogue.editor.keys.KeyTranslator` and
:class:`~coderogue.editor.keys.KeyRepeater`. In NORMAL mode the scene intercepts ``?`` (next
hint), ``Tab`` (next language) and ``r`` (raw error toggle); ex commands (``:w``, ``:q``,
``:wq``, ``:hint``, ``:skip``, ``:help``, ``:lang X``) arrive through ``on_command``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import pygame

from coderogue.editor.buffer import Buffer
from coderogue.editor.keys import KeyRepeater, KeyTranslator
from coderogue.editor.render import EditorTheme, EditorView
from coderogue.editor.vim import Mode, VimEditor
from coderogue.languages import LANGUAGE_IDS, available, registry
from coderogue.progress import HINT_RUNGS, Progress
from coderogue.puzzles import PuzzleResult, RunnerError, diff_summary, run_puzzle
from coderogue.scene import Scene
from coderogue.ui import theme
from coderogue.ui.panels import draw_panel, live_font, wrap_text

if TYPE_CHECKING:
    from coderogue.app import Game
    from coderogue.entities.altar import Altar
    from coderogue.puzzles import LanguageVariant, PuzzleBody, PuzzleSpec, TestOutcome

SKIP_AFTER_S = 600.0  # :skip is offered after 10 minutes at an altar (or after rung 3)
CLOSE_DELAY_S = 2.0  # the scene closes this long after the altar lights (or on any key)
NUDGE_AFTER_FAILS = 2  # Moth offers a hint after this many failed casts in a row
SKIP_BANNER = "Pell's solution, trace it or :q"

TOP_RECT = pygame.Rect(16, 10, 928, 116)
EDITOR_RECT = pygame.Rect(16, 132, 928, 240)
PANE_RECT = pygame.Rect(16, 378, 928, 152)

HELP_LINES: tuple[tuple[str, str], ...] = (
    ("i  a  o", "start writing (INSERT)"),
    ("Esc", "back to NORMAL"),
    ("h j k l  w b e  0 $", "move"),
    ("x  dd  u  Ctrl-r", "delete char / line, undo, redo"),
    (":w", "cast the spell"),
    (":wq", "cast, and leave if it works"),
    (":q", "leave (your draft is kept)"),
    ("?  or  :hint", "Moth's next hint (3 rungs)"),
    ("Tab  or  :lang bash", "switch language (separate drafts)"),
    ("r", "show the Terminal's exact words"),
    (":skip", "Pell's solution (after hint 3)"),
)

Pane = str  # "intro" | "hint" | "result" | "notice" | "skip"


class AltarScene(Scene):
    """Modal puzzle editor for one altar. Time in the world below is frozen."""

    transparent = True

    def __init__(
        self,
        game: Game,
        world: Any,
        altar: Altar,
        spec: PuzzleSpec,
        progress: Progress,
        language: str | None = None,
        start_phase: int | None = None,
        single_phase: bool = False,
    ) -> None:
        super().__init__(game)
        self.world = world
        self.altar = altar
        self.spec = spec
        self.progress = progress
        self.phase: int | None = 0 if spec.is_boss else None
        if spec.is_boss and start_phase is not None:
            self.phase = max(0, min(start_phase, len(spec.phases) - 1))
        # One lectern per phase: close after this phase instead of moving on to the next.
        self.single_phase = single_phase and spec.is_boss
        self.offered = spec.language_ids()
        avail = available()
        self.usable: list[str] = []
        self.too_old: dict[str, str] = {}  # language id -> "needs bash >=4, found 3.2"
        for lid in self.offered:
            if lid not in avail:
                continue
            spec_req = spec.requires.get(lid)
            runtime = avail[lid].detect()
            if spec_req and runtime is not None and not avail[lid].version_satisfies(
                runtime, spec_req
            ):
                self.too_old[lid] = f"needs {lid} {spec_req}, found {runtime.version_str}"
                continue
            self.usable.append(lid)
        self.solved_view = progress.is_solved(spec.id)
        self.editors: dict[str, VimEditor] = {}
        self.views: dict[str, EditorView] = {}
        self.font = live_font(16)
        self.small = live_font(14)
        self.bold = live_font(18, bold=True)
        self.editor_theme = EditorTheme(background=(18, 17, 24), gutter_bg=(24, 22, 32))
        self.translator = KeyTranslator()
        self.repeater = KeyRepeater()
        self.result: PuzzleResult | None = None
        self.pane: Pane = "intro"
        self.notice = ""
        self.hint_shown = 0  # rung currently in Moth's bubble (0 = none)
        self.show_raw = False
        self.show_help = False
        self.chanting = False
        self.closing: float | None = None  # seconds until auto-close after a pass
        self.failed_casts = 0
        self.time_here = 0.0
        self.skip_lang: str | None = None
        self.xp_gained = 0
        self.left = False
        self.language = self._initial_language(language)
        self._editor_for(self.language)

    # ---- setup ------------------------------------------------------------------------
    def _initial_language(self, wanted: str | None) -> str:
        if wanted in self.usable:
            return str(wanted)
        if self.solved_view:
            for lid in self.usable:
                if self.progress.is_solved(self.spec.id, lid):
                    return lid
        if self.usable:
            return self.usable[0]
        return self.offered[0] if self.offered else LANGUAGE_IDS[0]

    @property
    def body(self) -> PuzzleBody:
        """The puzzle body being solved (the current phase for a boss)."""
        return self.spec.body_for(self.phase)

    def variant(self, lid: str | None = None) -> LanguageVariant | None:
        """The puzzle's code/hints/solution for ``lid`` (default: current language)."""
        return self.body.languages.get(lid or self.language)

    @property
    def draft_key(self) -> str:
        """Key the drafts are stored under: ``<id>`` or ``<id>#<phase>`` for a boss phase,
        so each lectern keeps its own code."""
        return self.spec.id if self.phase is None else f"{self.spec.id}#{self.phase}"

    def _initial_text(self, lid: str) -> str:
        draft = self.progress.draft(self.draft_key, lid)
        if draft is not None:
            return draft
        variant = self.variant(lid)
        if variant is None:
            return ""
        if self.progress.is_solved(self.spec.id, lid):
            return variant.solution.rstrip("\n")
        return variant.starter.rstrip("\n")

    def _editor_for(self, lid: str) -> VimEditor:
        editor = self.editors.get(lid)
        if editor is None:
            editor = VimEditor(Buffer(self._initial_text(lid)), on_command=self.on_command)
            self.editors[lid] = editor
            self.views[lid] = EditorView(editor, self.font, language=lid)
        return editor

    @property
    def editor(self) -> VimEditor:
        """The editor for the current language."""
        return self._editor_for(self.language)

    @property
    def view(self) -> EditorView:
        """The view for the current language."""
        self._editor_for(self.language)
        return self.views[self.language]

    # ---- scene hooks ------------------------------------------------------------------
    def on_enter(self) -> None:
        """Editor has focus: receive TEXTINPUT events."""
        pygame.key.start_text_input()

    def on_exit(self) -> None:
        """Editor loses focus; keep the drafts."""
        self.save_drafts()
        self.repeater.reset()
        pygame.key.stop_text_input()

    # ---- input ------------------------------------------------------------------------
    def handle_event(self, event: pygame.event.Event) -> None:
        """Route key events through the translator to the editor (or the scene's keys)."""
        if event.type == pygame.WINDOWFOCUSLOST:
            self.repeater.reset()
            return
        if event.type == pygame.KEYUP:
            self.repeater.release(event.key)
            return
        if event.type not in (pygame.KEYDOWN, pygame.TEXTINPUT):
            return
        if event.type == pygame.KEYDOWN and self.closing is not None:
            self.leave()
            return
        if event.type == pygame.KEYDOWN and self.show_help:
            self.show_help = False
            self.translator.translate(event, self.editor.mode)  # arm the echo swallow
            return
        mode = self.editor.mode
        keys = self.translator.translate(event, mode)
        if event.type == pygame.KEYDOWN:
            self.repeater.press(event.key, keys[0] if keys else None, mode)
        for key in keys:
            if self.left:
                break
            self.feed(key)

    def feed(self, key: str) -> None:
        """Process one translated key string."""
        editor = self.editor
        if editor.mode is Mode.NORMAL and not editor.pending:
            if key == "?":
                self.next_hint()
                return
            if key == "<Tab>":
                self.cycle_language()
                return
            if key == "r" and self.has_raw_error:
                self.show_raw = not self.show_raw
                return
        editor.feed_key(key)

    def on_command(self, command: str) -> None:
        """Ex commands typed in the editor (without the leading ``:``)."""
        parts = command.split()
        if not parts:
            return
        name, args = parts[0], parts[1:]
        if name in ("w", "write"):
            self.cast()
        elif name in ("q", "q!", "quit"):
            self.leave()
        elif name in ("wq", "x", "wq!"):
            if self.cast():
                self.leave()
        elif name == "hint":
            self.next_hint()
        elif name == "skip":
            self.skip()
        elif name in ("help", "h"):
            self.show_help = True
        elif name in ("lang", "language", "set_lang"):
            if args:
                self.switch_language(args[0])
            else:
                self.editor.last_message = "Usage: :lang " + "|".join(self.offered)
        else:
            self.editor.last_message = f"E492: Not an altar command: {command}"

    # ---- actions ----------------------------------------------------------------------
    @property
    def has_raw_error(self) -> bool:
        """True when the result pane has raw stderr to toggle."""
        return self.pane == "result" and self.result is not None and bool(
            self.result.raw_stderr.strip()
        )

    def next_hint(self) -> int:
        """Show Moth's next hint rung (1 -> 2 -> 3 -> 1...). Returns the rung shown."""
        variant = self.variant()
        if variant is None:
            return 0
        reached = self.progress.hint_rung(self.spec.id, self.language)
        if self.hint_shown == 0 and reached > 0:
            rung = reached
        else:
            rung = self.hint_shown % HINT_RUNGS + 1
        self.hint_shown = rung
        self.progress.note_hint(self.spec.id, self.language, rung)
        self.pane = "hint"
        return rung

    def cycle_language(self) -> None:
        """Switch to the next usable language (Tab)."""
        if len(self.usable) < 2:
            self.editor.last_message = "This altar speaks only one tongue here."
            return
        i = self.usable.index(self.language) if self.language in self.usable else -1
        self.switch_language(self.usable[(i + 1) % len(self.usable)])

    def switch_language(self, lid: str) -> bool:
        """Switch the editor to ``lid`` (its own draft). Returns True on success."""
        lid = lid.lower()
        if lid not in registry():
            self.editor.last_message = f"Unknown language: {lid}"
            return False
        name = registry()[lid].display_name
        if lid not in self.offered:
            self.editor.last_message = f"This altar does not speak {name}."
            return False
        if lid not in self.usable:
            reason = self.too_old.get(lid)
            self.editor.last_message = (
                f"{name} here is too old: {reason}." if reason
                else f"{name} was not found on this computer."
            )
            return False
        if lid == self.language:
            return True
        self.save_drafts()
        self.repeater.reset()
        self.language = lid
        self._editor_for(lid).last_message = f"Now writing {name}."
        self.result = None
        self.hint_shown = 0
        self.show_raw = False
        self.pane = "intro"
        return True

    def cast(self) -> bool:
        """Run the editor text against the puzzle. Returns True if the altar lit."""
        if self.language not in self.usable:
            name = registry()[self.language].display_name if self.language in registry() else ""
            self.notice = f"{name or self.language} was not found on this computer."
            self.pane = "notice"
            return False
        code = self.editor.text
        if not code.endswith("\n"):
            code += "\n"
        self.chanting = True
        self._present_now()
        try:
            result = run_puzzle(self.spec, self.language, code, self.phase)
        except RunnerError as exc:
            self.notice = str(exc)
            self.pane = "notice"
            return False
        finally:
            self.chanting = False
        self.result = result
        self.show_raw = False
        self.pane = "result"
        view = self.view
        view.error_lines = set()
        if result.passed:
            self.failed_casts = 0
            return self._on_pass(result)
        self.failed_casts += 1
        line = result.error_line or result.blank_line
        if line:
            view.error_lines = {line - 1}
        return False

    def _on_pass(self, result: PuzzleResult) -> bool:
        if self.phase is not None:
            self.progress.flags.add(f"phase:{self.spec.id}:{self.phase}")
            hook = getattr(self.world, "on_boss_phase_solved", None)
            if hook is not None:
                hook(self.spec, self.phase)
        if self.phase is not None and self.phase + 1 < len(self.spec.phases):
            if self.single_phase:
                self.progress.set_draft(self.draft_key, self.language, self.editor.text)
                self.editor.last_message = f"Phase {self.phase + 1} cleared! Find the next lectern."
                self.closing = CLOSE_DELAY_S
                return True
            self.save_drafts()  # keep this phase's code under its own key
            self.phase += 1
            for lid, editor in self.editors.items():
                editor.set_text(self._initial_text(lid))
            self.editor.last_message = f"Phase {self.phase} cleared! The next phase begins."
            self.hint_shown = 0
            return False
        before = self.progress.xp
        self.progress.mark_solved(self.spec.id, self.language, xp=self.spec.reward.xp)
        self.xp_gained = self.progress.xp - before
        self.progress.set_draft(self.draft_key, self.language, self.editor.text)
        self.altar.lit = True
        hook = getattr(self.world, "on_puzzle_solved", None)
        if hook is not None:
            hook(self.spec, result)
        self.closing = CLOSE_DELAY_S
        return True

    @property
    def can_skip(self) -> bool:
        """``:skip`` is offered after hint rung 3 was viewed, or after 10 minutes here."""
        return (
            self.progress.hint_rung(self.spec.id, self.language) >= HINT_RUNGS
            or self.time_here >= SKIP_AFTER_S
        )

    def skip(self) -> bool:
        """Mark the puzzle skipped and show Pell's solution. Returns True if allowed."""
        if not self.can_skip:
            self.editor.last_message = "Pell is not ready yet: see all 3 hints first (?)."
            return False
        variant = self.variant()
        if variant is None:
            return False
        self.progress.set_draft(self.draft_key, self.language, self.editor.text)
        self.progress.mark_skipped(self.spec.id)
        self.editor.set_text(variant.solution.rstrip("\n"))
        self.view.error_lines = set()
        self.skip_lang = self.language
        self.pane = "skip"
        self.result = None
        hook = getattr(self.world, "on_puzzle_skipped", None)
        if hook is not None:
            hook(self.spec)
        return True

    def save_drafts(self) -> None:
        """Store every opened editor's text in the progress (not Pell's shown solution)."""
        for lid, editor in self.editors.items():
            if lid == self.skip_lang:
                continue
            self.progress.set_draft(self.draft_key, lid, editor.text)

    def leave(self) -> None:
        """Pop the altar scene (drafts are kept)."""
        if self.left:
            return
        self.left = True
        self.save_drafts()
        if self.game.scene is self:
            self.game.pop()

    def _present_now(self) -> None:
        """Show the "chanting..." frame before the (synchronous) run starts."""
        if getattr(self.game, "headless", True) or self.game.scene is not self:
            return
        if pygame.display.get_surface() is None:
            return
        self.game.draw()

    # ---- simulation -------------------------------------------------------------------
    def update(self, dt: float) -> None:
        """Key repeat, the skip timer and the auto-close after a pass."""
        self.time_here += dt
        for key in self.repeater.update(dt, self.editor.mode):
            self.feed(key)
        if self.closing is not None:
            self.closing -= dt
            if self.closing <= 0:
                self.leave()

    # ---- rendering --------------------------------------------------------------------
    def draw(self, surface: pygame.Surface) -> None:
        """Scrim over the world, then lore strip, editor and result pane."""
        scrim = pygame.Surface(surface.get_size(), pygame.SRCALPHA)
        scrim.fill((0, 0, 0, theme.SCRIM_ALPHA))
        surface.blit(scrim, (0, 0))
        self._draw_top(surface)
        self.view.draw(surface, EDITOR_RECT, self.editor_theme)
        pygame.draw.rect(surface, theme.BORDER, EDITOR_RECT.inflate(2, 2), 1)
        self._draw_pane(surface)
        if self.show_help:
            self._draw_help(surface)

    def _text(
        self,
        surface: pygame.Surface,
        text: str,
        pos: tuple[int, int],
        color: tuple[int, int, int] = theme.TEXT,
        font: pygame.font.Font | None = None,
    ) -> pygame.Rect:
        surf = (font or self.small).render(text, True, color)
        return surface.blit(surf, pos)

    def _draw_top(self, surface: pygame.Surface) -> None:
        rect = draw_panel(surface, TOP_RECT, theme.PANEL, theme.BORDER)
        title = self.spec.title
        if self.phase is not None:
            title += f"  (phase {self.phase + 1}/{len(self.spec.phases)})"
        self._text(surface, title, (rect.x + 10, rect.y + 6), theme.GOLD, self.bold)
        # Language tabs, right-aligned.
        x = rect.right - 10
        for lid in reversed(LANGUAGE_IDS):
            usable = lid in self.usable
            star = "*" if self.progress.is_solved(self.spec.id, lid) else ""
            label = f"[{lid}{star}]" if lid == self.language else f" {lid}{star} "
            color = theme.ACCENT if lid == self.language else (theme.TEXT if usable else theme.DIM)
            surf = self.font.render(label, True, color)
            x -= surf.get_width()
            surface.blit(surf, (x, rect.y + 7))
            x -= 8
        lh = self.small.get_linesize()
        y = rect.y + 34
        lines = wrap_text(self.small, self.body.lore.strip(), rect.width - 20)
        max_lines = (rect.bottom - y - 4) // lh
        for line in lines[:max_lines]:
            self._text(surface, line, (rect.x + 10, y), theme.TEXT)
            y += lh

    def _draw_pane(self, surface: pygame.Surface) -> None:
        rect = draw_panel(surface, PANE_RECT, theme.PANEL, theme.BORDER)
        inner = rect.inflate(-20, -12)
        if self.chanting:
            self._text(surface, "chanting...", inner.topleft, theme.GOLD, self.font)
            return
        if self.pane == "skip":
            self._text(surface, SKIP_BANNER, inner.topleft, theme.GOLD, self.font)
            self._bubble(surface, inner.move(0, 28), "Pell", "Read it line by line. Retype "
                         "it yourself (:w) to light the altar for half the XP, or :q.")
            return
        if self.pane == "notice":
            self._bubble(surface, inner, "Moth", self.notice, theme.WARN)
            return
        if self.pane == "hint" and self.hint_shown:
            variant = self.variant()
            text = variant.hints[self.hint_shown - 1] if variant else ""
            label = f"Moth (hint {self.hint_shown}/{HINT_RUNGS})"
            if self.hint_shown == HINT_RUNGS and self.can_skip:
                text += "\n(Still stuck? :skip shows Pell's solution.)"
            self._bubble(surface, inner, label, text)
            return
        if self.pane == "result" and self.result is not None:
            self._draw_result(surface, inner, self.result)
            return
        # Intro.
        if self.solved_view:
            langs = ", ".join(sorted(self.progress.solved.get(self.spec.id, set())))
            msg = f"This altar is lit ({langs})."
            if len(self.usable) > 1 and not self.progress.is_bilingual(self.spec.id):
                msg += " Press Tab and cast in another tongue for a Bilingual star."
            self._text(surface, msg, inner.topleft, theme.ACCENT, self.font)
            inner = inner.move(0, 28)
        skill = f"Skill: {self.spec.vim_skill}.  " if self.spec.vim_skill else ""
        self._bubble(surface, inner, "Moth", f"{skill}Press i to write, Esc to stop, :w to "
                     "cast. ? for a hint, :help for keys, :q to leave.")

    def _bubble(
        self,
        surface: pygame.Surface,
        rect: pygame.Rect,
        speaker: str,
        text: str,
        color: tuple[int, int, int] = theme.TEXT,
    ) -> None:
        """Moth's (or Pell's) speech bubble with a small tail on the left."""
        lh = self.small.get_linesize()
        lines = wrap_text(self.small, text, rect.width - 40)
        max_lines = max(1, (rect.height - 30) // lh)
        lines = lines[:max_lines]
        box = pygame.Rect(rect.x + 12, rect.y, rect.width - 12, 26 + lh * len(lines))
        box.height = min(box.height, rect.height)
        draw_panel(surface, box, theme.PANEL_ALT, theme.ACCENT)
        tail = [(box.x, box.y + 10), (box.x - 10, box.y + 16), (box.x, box.y + 20)]
        pygame.draw.polygon(surface, theme.PANEL_ALT, tail)
        pygame.draw.lines(surface, theme.ACCENT, False, tail)
        self._text(surface, speaker + ":", (box.x + 10, box.y + 4), theme.ACCENT)
        y = box.y + 22
        for line in lines:
            self._text(surface, line, (box.x + 10, y), color)
            y += lh

    def _draw_result(self, surface: pygame.Surface, rect: pygame.Rect, res: PuzzleResult) -> None:
        lh = self.small.get_linesize()
        if res.passed:
            self._text(surface, "The altar lights.", rect.topleft, theme.ACCENT, self.bold)
            reward = self.spec.reward
            parts = []
            if self.xp_gained:
                parts.append(f"+{self.xp_gained} XP")
            if self.progress.is_bilingual(self.spec.id):
                parts.append("Bilingual star!")
            if reward.world_effect:
                parts.append(reward.world_effect)
            y = rect.y + 30
            for line in wrap_text(self.small, "  ".join(parts), rect.width):
                self._text(surface, line, (rect.x, y), theme.TEXT)
                y += lh
            self._text(surface, "(any key to return)", (rect.x, rect.bottom - lh), theme.MUTED)
            return
        if res.blank_detected:
            self._bubble(surface, rect, "Moth", res.message)
            return
        failure = res.first_failure
        y = rect.y
        if failure is not None:
            head = f"Test failed: {failure.name}"
            if failure.stdin:
                head += "    stdin: " + failure.stdin.rstrip("\n").replace("\n", " / ")
            self._text(surface, head, (rect.x, y), theme.WARN)
            y += lh + 2
        body = pygame.Rect(rect.x, y, rect.width, rect.bottom - y)
        if res.raw_stderr.strip() and (res.error_translation or self.show_raw):
            if self.show_raw:
                self._draw_raw(surface, body, res.raw_stderr)
            else:
                assert res.error_translation is not None
                self._bubble(surface, body.inflate(0, -lh), "Moth", res.error_translation)
            label = "[r] hide raw" if self.show_raw else "[r] raw: the Terminal's exact words"
            self._text(surface, label, (rect.x, rect.bottom - lh), theme.MUTED)
            return
        if failure is not None and failure.kind in ("stdout", "file_content"):
            self._draw_diff(surface, body, failure)
            return
        msg = res.message
        if self.failed_casts >= NUDGE_AFTER_FAILS and self.hint_shown == 0:
            msg += "  (Stuck? Press ? and I'll give you a hint.)"
        if res.raw_stderr.strip():
            msg += "  [r] raw"
        self._bubble(surface, body, "Moth", msg, theme.TEXT)

    def _draw_raw(self, surface: pygame.Surface, rect: pygame.Rect, stderr: str) -> None:
        lh = self.small.get_linesize()
        lines: list[str] = []
        for raw in stderr.rstrip().splitlines():
            lines.extend(wrap_text(self.small, raw, rect.width - 8))
        rows = max(1, (rect.height - lh) // lh)
        y = rect.y
        for line in lines[-rows:]:
            self._text(surface, line, (rect.x + 4, y), theme.ERROR)
            y += lh

    def _draw_diff(self, surface: pygame.Surface, rect: pygame.Rect, failure: TestOutcome) -> None:
        """Expected / Your spell said, side by side, first differing line highlighted."""
        diff = failure.diff or diff_summary(failure.expected, failure.actual, failure.match)
        lh = self.small.get_linesize()
        col_w = rect.width // 2
        self._text(surface, "Expected", (rect.x, rect.y), theme.MUTED)
        self._text(surface, "Your spell said", (rect.x + col_w, rect.y), theme.MUTED)
        y = rect.y + lh
        rows = list(diff.rows)
        visible = max(1, (rect.bottom - y) // lh)
        start = 0
        if diff.first_diff_line is not None:
            start = max(0, min(diff.first_diff_line - 1, len(rows) - visible))
        if not rows:
            self._text(surface, "(nothing)", (rect.x, y), theme.DIM)
        for row in rows[start : start + visible]:
            highlight = row.line_no == diff.first_diff_line
            if highlight:
                surface.fill(theme.DIFF_HIGHLIGHT, (rect.x - 4, y, rect.width + 8, lh))
            for i, text in enumerate((row.expected, row.actual)):
                x = rect.x + i * col_w
                shown = "(no line)" if text is None else text
                color = theme.DIM if text is None else (
                    theme.WARN if row.differs else theme.TEXT
                )
                clip = surface.get_clip()
                surface.set_clip(pygame.Rect(x, y, col_w - 8, lh).clip(clip))
                self._text(surface, f"{row.line_no:>2} {shown}", (x, y), color)
                surface.set_clip(clip)
            y += lh
        if self.failed_casts >= NUDGE_AFTER_FAILS and self.hint_shown == 0:
            hint = "Moth: stuck? Press ? for a hint."
            surf = self.small.render(hint, True, theme.ACCENT)
            surface.blit(surf, (rect.right - surf.get_width(), rect.y))

    def _draw_help(self, surface: pygame.Surface) -> None:
        lh = self.small.get_linesize() + 2
        w, h = 600, 56 + lh * (len(HELP_LINES) + 1)
        sw, sh = surface.get_size()
        rect = pygame.Rect((sw - w) // 2, (sh - h) // 2, w, h)
        draw_panel(surface, rect, theme.PANEL, theme.ACCENT, 2)
        self._text(surface, "Altar keys", (rect.x + 16, rect.y + 10), theme.GOLD, self.bold)
        y = rect.y + 40
        for keys, what in HELP_LINES:
            self._text(surface, keys, (rect.x + 16, y), theme.ACCENT)
            self._text(surface, what, (rect.x + 240, y), theme.TEXT)
            y += lh
        self._text(surface, "(any key to close)", (rect.x + 16, rect.bottom - lh - 4), theme.MUTED)
