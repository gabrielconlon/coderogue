"""Run one player script in a throwaway directory and capture what it did.

THIS IS NOT A SECURITY BOUNDARY. It keeps honest mistakes (infinite loops, runaway output,
huge files, fork loops, stray writes into the working tree) from hurting the game or the
machine. Code that wants to escape can: it runs as the player's own user with their file
permissions. That is acceptable because the only code run here is code the player typed
themselves or the game's own reference solutions.

What it does:

* a fresh ``tempfile.TemporaryDirectory`` is the cwd, with fixtures and the script written in;
* a scrubbed environment: ``PATH`` (the interpreter's directory plus standard bins),
  ``HOME`` = the temp dir, ``LANG=C.UTF-8``, ``PYTHONIOENCODING=utf-8`` and nothing else
  (Windows additionally gets the handful of variables processes need to start, see
  :mod:`sandbox_win`);
* POSIX: a new session (``start_new_session=True``) so a timeout kills the whole process group
  with ``os.killpg``; rlimits (CPU = timeout + 1 s, file size 8 MB, 64 open files, a process
  cap on Linux) applied by a launcher shim (:mod:`sandbox_posix`), never ``preexec_fn``;
  ``unshare -rn`` cuts the network on Linux where permitted. macOS has no network block (the
  only tool, ``sandbox-exec``, is deprecated);
* Windows: a new process group, ``taskkill /T /F`` on timeout;
* stdout and stderr are each captured up to ``max_output_bytes``. Output beyond that marks the
  result ``output_truncated`` and stops the script early, so a print loop cannot eat memory.
  Pipes are drained by reader threads rather than ``communicate()`` for that reason.
"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import threading
import time
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import IO, Any

from coderogue.languages import Language, LanguageRuntime

if sys.platform == "win32":
    from coderogue.puzzles import sandbox_win as _plat
else:
    from coderogue.puzzles import sandbox_posix as _plat

#: Files captured after the run are cut to this many bytes each.
MAX_CAPTURED_FILE_BYTES = 256 * 1024
_CHUNK = 8192


@dataclass
class ExecResult:
    """Everything observable about one run."""

    stdout: str
    stderr: str
    exit_code: int | None
    timed_out: bool = False
    output_truncated: bool = False
    #: Relative POSIX path -> text content of every file left in the temp dir (minus the script).
    files: dict[str, str] = field(default_factory=dict)
    duration_s: float = 0.0


class _CappedReader(threading.Thread):
    """Drains one pipe, keeping at most ``cap`` bytes; calls ``on_overflow`` once if exceeded."""

    def __init__(self, stream: IO[bytes], cap: int, on_overflow: Any) -> None:
        super().__init__(daemon=True)
        self.stream = stream
        self.cap = cap
        self.on_overflow = on_overflow
        self.buf = bytearray()
        self.overflowed = False

    def run(self) -> None:
        try:
            while True:
                chunk = self.stream.read1(_CHUNK) if hasattr(self.stream, "read1") else (
                    self.stream.read(_CHUNK))
                if not chunk:
                    break
                room = self.cap - len(self.buf)
                if len(chunk) > room:
                    self.buf += chunk[: max(room, 0)]
                    if not self.overflowed:
                        self.overflowed = True
                        self.on_overflow()
                else:
                    self.buf += chunk
        except (OSError, ValueError):
            pass


def _fixture_items(fixtures: Any) -> list[tuple[str, str]]:
    if not fixtures:
        return []
    if isinstance(fixtures, Mapping):
        return [(str(k), str(v)) for k, v in fixtures.items()]
    items: list[tuple[str, str]] = []
    for f in fixtures:
        if isinstance(f, tuple):
            items.append((str(f[0]), str(f[1])))
        else:
            items.append((f.path, f.content))
    return items


def _safe_join(root: Path, rel: str) -> Path:
    p = PurePosixPath(rel.replace("\\", "/"))
    if p.is_absolute() or ".." in p.parts or not p.parts:
        raise ValueError(f"fixture path must stay inside the sandbox: {rel!r}")
    return root.joinpath(*p.parts)


def _write_text(path: Path, text: str, encoding: str = "utf-8") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    # newline="" keeps "\n" as-is on Windows so bash scripts do not get CRLF.
    with open(path, "w", encoding=encoding, newline="") as fh:
        fh.write(text)


def build_env(runtime: LanguageRuntime, tmpdir: str) -> dict[str, str]:
    """The scrubbed environment for a run."""
    dirs = [os.path.dirname(runtime.executable), *_plat.base_path_dirs()]
    path: list[str] = []
    for d in dirs:
        if d and d not in path:
            path.append(d)
    env = {
        "PATH": os.pathsep.join(path),
        "HOME": tmpdir,
        "LANG": "C.UTF-8",
        "PYTHONIOENCODING": "utf-8",
    }
    env.update(_plat.extra_env(tmpdir))
    return env


def _collect_files(root: Path, skip: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for p in sorted(root.rglob("*")):
        if not p.is_file() or p.is_symlink():
            continue
        rel = p.relative_to(root).as_posix()
        if rel == skip:
            continue
        try:
            with open(p, "rb") as fh:
                data = fh.read(MAX_CAPTURED_FILE_BYTES)
        except OSError:
            continue
        out[rel] = data.decode("utf-8", errors="replace").replace("\r\n", "\n")
    return out


def _scrub_paths(text: str, tmpdir: str) -> str:
    """Remove the temp-dir prefix so errors read ``main.py`` rather than a long path."""
    for prefix in {tmpdir, os.path.realpath(tmpdir)}:
        text = text.replace(prefix + os.sep, "").replace(prefix + "/", "")
    return text


def run_script(
    language: Language,
    runtime: LanguageRuntime,
    code: str,
    stdin: str = "",
    fixtures: Iterable[Any] | Mapping[str, str] | None = None,
    timeout_s: float = 2.0,
    max_output_bytes: int = 16 * 1024,
) -> ExecResult:
    """Run ``code`` as ``language`` in a fresh temp dir and return what happened.

    ``fixtures`` may be a mapping ``{path: content}``, ``(path, content)`` pairs, or objects
    with ``.path`` and ``.content`` (e.g. :class:`coderogue.puzzles.spec.Fixture`).
    """
    with tempfile.TemporaryDirectory(prefix="coderogue-", ignore_cleanup_errors=True) as tmpdir:
        root = Path(tmpdir)
        for rel, content in _fixture_items(fixtures):
            _write_text(_safe_join(root, rel), content)
        script = root / language.file_name
        _write_text(script, code, language.script_encoding)

        argv = language.command(runtime, language.file_name)
        argv[-1] = str(script)
        if sys.platform != "win32":
            argv = [*_plat.network_prefix(), *_plat.rlimit_prefix(timeout_s), *argv]

        start = time.monotonic()
        try:
            proc = subprocess.Popen(
                argv,
                cwd=tmpdir,
                env=build_env(runtime, tmpdir),
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                **_plat.popen_kwargs(),  # type: ignore[arg-type]
            )
        except OSError as exc:
            return ExecResult("", f"could not start {runtime.executable}: {exc}", None,
                              duration_s=time.monotonic() - start)

        overflow = threading.Event()

        def _on_overflow() -> None:
            overflow.set()
            _plat.kill_tree(proc)

        assert proc.stdout is not None and proc.stderr is not None and proc.stdin is not None
        readers = [
            _CappedReader(proc.stdout, max_output_bytes, _on_overflow),
            _CappedReader(proc.stderr, max_output_bytes, _on_overflow),
        ]
        for r in readers:
            r.start()

        def _feed(pipe: IO[bytes], data: bytes) -> None:
            try:
                if data:
                    pipe.write(data)
                    pipe.flush()
            except (BrokenPipeError, OSError, ValueError):
                pass
            finally:
                try:
                    pipe.close()
                except OSError:
                    pass

        writer = threading.Thread(
            target=_feed, args=(proc.stdin, stdin.encode("utf-8")), daemon=True
        )
        writer.start()

        timed_out = False
        try:
            proc.wait(timeout=timeout_s + language.startup_allowance_s)
        except subprocess.TimeoutExpired:
            timed_out = not overflow.is_set()
            _plat.kill_tree(proc)
            proc.wait()
        if sys.platform != "win32":
            # Reap anything the script left running in the background.
            _plat.kill_tree(proc)
        for r in readers:
            r.join(timeout=2.0)
        writer.join(timeout=1.0)
        for pipe in (proc.stdout, proc.stderr):
            try:
                pipe.close()
            except OSError:
                pass
        duration = time.monotonic() - start

        stdout = readers[0].buf.decode("utf-8", errors="replace")
        stderr = _scrub_paths(readers[1].buf.decode("utf-8", errors="replace"), tmpdir)
        files = _collect_files(root, language.file_name)
        return ExecResult(
            stdout=stdout,
            stderr=stderr,
            exit_code=None if timed_out else proc.returncode,
            timed_out=timed_out,
            output_truncated=overflow.is_set(),
            files=files,
            duration_s=duration,
        )
