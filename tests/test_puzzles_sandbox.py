"""The sandbox, with real subprocesses (python always; bash when installed)."""

from __future__ import annotations

import sys
import time

import pytest

from coderogue.languages import get
from coderogue.puzzles.sandbox import build_env, run_script
from coderogue.puzzles.spec import Fixture

PY = get("python")
PY_RT = PY.detect()
BASH = get("bash")
BASH_RT = BASH.detect()
needs_bash = pytest.mark.skipif(BASH_RT is None, reason="bash not installed")


def py(code: str, stdin: str = "", **kw: object):  # type: ignore[no-untyped-def]
    assert PY_RT is not None
    return run_script(PY, PY_RT, code, stdin, **kw)  # type: ignore[arg-type]


def test_echo_stdin_and_exit_code() -> None:
    r = py("import sys\nprint(input().upper())\nsys.exit(3)\n", "wren\n")
    assert r.stdout == "WREN\n"
    assert r.exit_code == 3
    assert not r.timed_out and not r.output_truncated
    assert r.duration_s < 5


def test_unicode_round_trip() -> None:
    r = py("print(input() + ' ✓')\n", "Wrén\n")
    assert r.stdout == "Wrén ✓\n"


def test_stderr_paths_are_scrubbed() -> None:
    r = py("prnt('x')\n")
    assert r.exit_code == 1
    assert 'File "main.py", line 1' in r.stderr
    assert "coderogue-" not in r.stderr


def test_timeout_kills_infinite_loop() -> None:
    start = time.monotonic()
    r = py("while True:\n    pass\n", timeout_s=1.0)
    elapsed = time.monotonic() - start
    assert r.timed_out
    assert r.exit_code is None
    assert elapsed < 2.5


def test_output_is_capped() -> None:
    start = time.monotonic()
    r = py("while True:\n    print('spam' * 50)\n", timeout_s=3.0, max_output_bytes=4096)
    assert r.output_truncated
    assert not r.timed_out
    assert len(r.stdout.encode()) <= 4096
    assert time.monotonic() - start < 3.0  # stopped early, not at the timeout


def test_fixtures_visible_and_written_files_captured() -> None:
    code = (
        "print(open('scroll.txt').read().strip())\n"
        "print(open('deep/note.txt').read().strip())\n"
        "open('ledger.txt', 'w').write('potion 3\\n')\n"
    )
    r = py(code, fixtures=[Fixture("scroll.txt", "The Null\n"), Fixture("deep/note.txt", "hi")])
    assert r.stdout == "The Null\nhi\n"
    assert r.files["ledger.txt"] == "potion 3\n"
    assert r.files["scroll.txt"] == "The Null\n"
    assert "main.py" not in r.files


def test_fixture_mapping_and_escape_rejected() -> None:
    r = py("print(open('a.txt').read())\n", fixtures={"a.txt": "A"})
    assert r.stdout == "A\n"
    with pytest.raises(ValueError):
        py("pass\n", fixtures={"../x.txt": "no"})


def test_each_run_gets_a_fresh_directory() -> None:
    py("open('left.txt', 'w').write('x')\n")
    r = py("import os\nprint(sorted(os.listdir('.')))\n")
    assert "left.txt" not in r.stdout


def test_env_is_scrubbed() -> None:
    r = py("import os\nprint(os.path.realpath(os.environ['HOME']) == os.getcwd())\n"
           "print(os.environ.get('LANG'))\nprint('SECRET_TOKEN' in os.environ)\n")
    assert r.stdout.split() == ["True", "C.UTF-8", "False"]
    assert PY_RT is not None
    env = build_env(PY_RT, "/tmp/x")
    assert env["HOME"] == "/tmp/x"
    if sys.platform != "win32":
        assert set(env) == {"PATH", "HOME", "LANG", "PYTHONIOENCODING"}


@pytest.mark.skipif(sys.platform == "win32", reason="rlimits are POSIX-only")
def test_rlimits_applied() -> None:
    r = py("import resource\nprint(resource.getrlimit(resource.RLIMIT_CPU)[0])\n"
           "print(resource.getrlimit(resource.RLIMIT_NOFILE)[0])\n", timeout_s=2.0)
    cpu, nofile = (int(x) for x in r.stdout.split())
    assert cpu == 3
    assert nofile <= 64


@needs_bash
def test_bash_stdin_files_and_errors() -> None:
    assert BASH_RT is not None
    code = 'read -r name\necho "Hi $name"\necho saved > out.txt\nehco oops\n'
    r = run_script(BASH, BASH_RT, code, "Wren\n", fixtures={"in.txt": "x"})
    assert r.stdout == "Hi Wren\n"
    assert r.files["out.txt"] == "saved\n"
    assert "main.sh: line 4: ehco: command not found" in r.stderr
    assert BASH.translate_error(r.stderr) is not None


@needs_bash
def test_bash_timeout_kills_background_children() -> None:
    assert BASH_RT is not None
    start = time.monotonic()
    r = run_script(BASH, BASH_RT, "sleep 30 &\nwhile true; do :; done\n", timeout_s=1.0)
    assert r.timed_out
    assert time.monotonic() - start < 2.5
