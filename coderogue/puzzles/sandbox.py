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
* POSIX: a new session (``start_new_session=True``) so the whole process group is killed with
  ``os.killpg`` when the script ends (any way: exit, timeout, output cap); processes that left
  the group (``setsid``) are found by a per-run environment tag (``CODEROGUE_RUN``, Linux) or
  a working directory inside the temp dir (Linux, macOS) and killed when they keep the
  output pipes open. rlimits (CPU = ceil(timeout + start-up allowance) +
  1 s, so the wall clock fires first; file size 8 MB; 64 open files, or the language's
  ``max_open_files``; a thread cap on Linux) are applied by a launcher shim
  (:mod:`sandbox_posix`), never ``preexec_fn``. A SIGXCPU death still counts as a timeout.
  ``unshare -rn`` cuts the network on Linux where permitted. macOS has no network block (the
  only tool, ``sandbox-exec``, is deprecated);
* Windows: a new process group inside a kill-on-close Job Object (``taskkill /T /F`` when no
  job could be made), so every descendant dies with the run;
* stdout and stderr are each captured up to ``max_output_bytes``. Output beyond that marks the
  result ``output_truncated`` and stops the script early, so a print loop cannot eat memory.
  Pipes are drained by reader threads rather than ``communicate()`` for that reason.
"""

from __future__ import annotations

import os
import stat
import subprocess
import sys
import tempfile
import threading
import time
import uuid
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import IO, Any

from coderogue.languages import Language, LanguageRuntime

if sys.platform == "win32":
    from coderogue.puzzles import sandbox_win as _plat
else:
    from coderogue.puzzles import sandbox_posix as _plat

#: Environment variable carrying a per-run tag (see :func:`sandbox_posix.kill_strays`).
RUN_TAG_VAR = "CODEROGUE_RUN"

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
        out[rel] = data.decode("utf-8-sig", errors="replace").replace("\r\n", "\n")
    return out


def _scrub_paths(text: str, tmpdir: str) -> str:
    """Remove the temp-dir prefix so errors read ``main.py`` rather than a long path."""
    for prefix in {tmpdir, os.path.realpath(tmpdir)}:
        text = text.replace(prefix + os.sep, "").replace(prefix + "/", "")
    return text


def _make_writable(path: str) -> None:
    """Best-effort ``chmod u+rwx`` on ``path`` and every directory under it (no symlinks), so
    a script that ``chmod 000``-ed something cannot make the temp dir undeletable."""
    try:
        st = os.lstat(path)
    except OSError:
        return
    if stat.S_ISLNK(st.st_mode):
        return
    try:
        os.chmod(path, stat.S_IMODE(st.st_mode) | stat.S_IRWXU)
    except OSError:
        pass
    if stat.S_ISDIR(st.st_mode):
        try:
            names = os.listdir(path)
        except OSError:
            return
        for name in names:
            _make_writable(os.path.join(path, name))


def _join_all(threads: Iterable[threading.Thread], timeout_s: float) -> bool:
    """Join ``threads`` within one shared deadline; True when all have finished."""
    deadline = time.monotonic() + timeout_s
    for t in threads:
        t.join(max(0.0, deadline - time.monotonic()))
    return not any(t.is_alive() for t in threads)


#: After the script exits, how long the readers get to hit EOF before strays are hunted down.
_DRAIN_GRACE_S = 0.25
#: ...and how long after that hunt before the readers are abandoned (they end at EOF later).
_DRAIN_AFTER_SWEEP_S = 1.0


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

    Whatever way the script ends, its whole process tree is killed before the output is read,
    so a background child (even one in its own session) cannot keep the pipes open and stall
    the game.
    """
    with tempfile.TemporaryDirectory(prefix="coderogue-", ignore_cleanup_errors=True) as tmpdir:
        root = Path(tmpdir)
        try:
            return _run_in(language, runtime, code, stdin, fixtures, timeout_s,
                           max_output_bytes, tmpdir, root)
        finally:
            _make_writable(tmpdir)


def _run_in(
    language: Language,
    runtime: LanguageRuntime,
    code: str,
    stdin: str,
    fixtures: Iterable[Any] | Mapping[str, str] | None,
    timeout_s: float,
    max_output_bytes: int,
    tmpdir: str,
    root: Path,
) -> ExecResult:
    for rel, content in _fixture_items(fixtures):
        _write_text(_safe_join(root, rel), content)
    script = root / language.file_name
    _write_text(script, code, language.script_encoding)

    budget_s = timeout_s + language.startup_allowance_s
    argv = language.command(runtime, language.file_name)
    argv[-1] = str(script)
    if sys.platform != "win32":
        argv = [*_plat.network_prefix(),
                *_plat.rlimit_prefix(budget_s, language.max_open_files), *argv]
    # Every process of this run inherits the tag, so escapees can be found (see kill_strays).
    tag = uuid.uuid4().hex
    env = build_env(runtime, tmpdir)
    env[RUN_TAG_VAR] = tag

    start = time.monotonic()
    try:
        proc = subprocess.Popen(
            argv,
            cwd=tmpdir,
            env=env,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            **_plat.popen_kwargs(),  # type: ignore[arg-type]
        )
    except OSError as exc:
        return ExecResult("", f"could not start {runtime.executable}: {exc}", None,
                          duration_s=time.monotonic() - start)
    job = _plat.attach(proc)
    try:
        overflow = threading.Event()

        def _on_overflow() -> None:
            overflow.set()
            _plat.kill_tree(proc, job)

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
            proc.wait(timeout=budget_s)
        except subprocess.TimeoutExpired:
            timed_out = not overflow.is_set()
        # Kill the whole tree on every exit, not just a timeout: anything the script left
        # running in the background would otherwise hold the pipes open.
        _plat.kill_tree(proc, job)
        proc.wait()
        if not _join_all(readers, _DRAIN_GRACE_S):
            # Someone outside the process group (a setsid child) still holds a pipe.
            _plat.kill_strays(f"{RUN_TAG_VAR}={tag}", tmpdir)
            _join_all(readers, _DRAIN_AFTER_SWEEP_S)
        writer.join(timeout=0.5)
        # Never close a pipe whose reader is still blocked in read(): close() would wait on
        # the reader's lock. A daemon reader ends by itself at EOF and its pipe is then freed.
        for r, pipe in zip(readers, (proc.stdout, proc.stderr), strict=True):
            if not r.is_alive():
                try:
                    pipe.close()
                except OSError:
                    pass
        duration = time.monotonic() - start
    finally:
        _plat.release(job)

    if not timed_out and _plat.is_cpu_limit_death(proc.returncode):
        # The CPU rlimit fired before the wall clock did: that is a timeout too.
        timed_out = True
    stdout = bytes(readers[0].buf).decode("utf-8", errors="replace")
    stderr = _scrub_paths(bytes(readers[1].buf).decode("utf-8", errors="replace"), tmpdir)
    _make_writable(tmpdir)
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
