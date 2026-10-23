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


# ---- review fixes: process trees, CPU limit, NPROC shim, cleanup ---------------------------

def _pids_running(pattern: str) -> list[str]:
    import subprocess

    out = subprocess.run(["ps", "-x", "-o", "pid=,command="], capture_output=True, text=True)
    return [ln for ln in out.stdout.splitlines() if pattern in ln and "ps -x" not in ln]


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX process sweep")
def test_setsid_grandchild_does_not_stall_and_is_killed() -> None:
    # A child in its own session survives killpg and holds the pipes open; the run must
    # still return promptly and the child must be gone.
    marker = "sleep 30.4242"
    code = ("import subprocess\n"
            f"subprocess.Popen({marker.split()!r}, start_new_session=True)\n"
            "print('hi')\n")
    start = time.monotonic()
    r = py(code, timeout_s=2.0)
    elapsed = time.monotonic() - start
    assert r.stdout == "hi\n" and r.exit_code == 0 and not r.timed_out
    assert elapsed < 1.5
    time.sleep(0.1)
    assert _pids_running(marker) == []


def test_background_child_in_group_is_killed_on_normal_exit() -> None:
    marker = "sleep 30.4343"
    code = f"import subprocess\nsubprocess.Popen({marker.split()!r})\nprint('ok')\n"
    start = time.monotonic()
    r = py(code, timeout_s=2.0)
    assert r.stdout == "ok\n"
    assert time.monotonic() - start < 1.5
    if sys.platform != "win32":
        time.sleep(0.1)
        assert _pids_running(marker) == []


@pytest.mark.skipif(sys.platform == "win32", reason="rlimits are POSIX-only")
def test_cpu_limit_covers_startup_allowance_and_sigxcpu_is_a_timeout() -> None:
    from coderogue.puzzles import sandbox_posix

    assert sandbox_posix.cpu_seconds(2.0) == 3
    assert sandbox_posix.cpu_seconds(2.0 + 2.0) == 5  # PowerShell: timeout + 2 s allowance
    assert sandbox_posix.cpu_seconds(2.5) == 4
    prefix = sandbox_posix.rlimit_prefix(4.0, 256)
    assert prefix[6:9] == ["5", str(sandbox_posix.FSIZE_BYTES), "256"]
    # A process killed by SIGXCPU reports as a timeout, not "code -24".
    r = py("import os, signal\nos.kill(os.getpid(), signal.SIGXCPU)\n", timeout_s=2.0)
    assert r.timed_out and r.exit_code is None


def test_powershell_gets_more_open_files() -> None:
    assert get("powershell").max_open_files == 256
    assert PY.max_open_files is None


def _shim_namespace() -> dict[str, object]:
    from coderogue.puzzles import sandbox_posix

    ns: dict[str, object] = {"__name__": "shim_under_test"}
    exec(sandbox_posix.RLIMIT_SHIM, ns)  # defines helpers only; the main block is skipped
    return ns


def test_nproc_shim_counts_threads_with_headroom_and_floor(tmp_path) -> None:  # type: ignore[no-untyped-def]
    import os

    ns = _shim_namespace()
    count = ns["_count_user_threads"]
    limit = ns["_nproc_limit"]
    uid = os.getuid() if hasattr(os, "getuid") else 0
    proc = tmp_path / "proc"
    for pid, threads in (("100", 3), ("200", 1500), ("300", 1)):
        for t in range(threads):
            (proc / pid / "task" / str(t)).mkdir(parents=True)
    (proc / "self").mkdir()  # non-numeric entries are ignored
    assert count(str(proc), uid, "linux") == 1504  # threads, not 3 processes
    assert count(str(proc), uid + 1, "linux") == 0  # other users' tasks are not counted
    assert count(str(proc), uid, "darwin") is None  # no cheap count: limit skipped
    assert limit(1504, 256, 1024) == 1760
    assert limit(10, 256, 1024) == 1024
    assert limit(None, 256, 1024) is None


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX permissions")
def test_chmod_000_does_not_leak_the_temp_dir() -> None:
    import os

    code = ("import os\nprint(os.getcwd())\nos.mkdir('vault')\n"
            "open('vault/gold.txt', 'w').write('x')\nos.chmod('vault', 0)\n")
    r = py(code)
    assert r.exit_code == 0
    assert r.files.get("vault/gold.txt") == "x"
    assert not os.path.exists(r.stdout.strip())


def test_windows_job_object_degrades_and_kill_tree_prefers_job(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    from coderogue.puzzles import sandbox_win

    class FakeProc:
        pid = 4242
        _handle = 0
        killed = False

        def kill(self) -> None:
            self.killed = True

    if sys.platform != "win32":
        # No kernel32 here: attach must degrade to None rather than raise.
        assert sandbox_win.attach(FakeProc()) is None  # type: ignore[arg-type]
    terminated: list[object] = []
    monkeypatch.setattr(sandbox_win, "_terminate_job", lambda job: terminated.append(job) or True)
    ran: list[list[str]] = []
    monkeypatch.setattr(sandbox_win.subprocess, "run", lambda argv, **kw: ran.append(argv))
    proc = FakeProc()
    sandbox_win.kill_tree(proc, job=1234)  # type: ignore[arg-type]
    assert terminated == [1234] and proc.killed and ran == []  # no taskkill needed
    monkeypatch.setattr(sandbox_win.shutil, "which", lambda name: "taskkill.exe")
    sandbox_win.kill_tree(proc, job=None)  # type: ignore[arg-type]
    assert ran and ran[0][:3] == ["taskkill.exe", "/T", "/F"]
    assert sandbox_win.kill_strays("CODEROGUE_RUN=x", "C:\\tmp") == 0
    assert sandbox_win.is_cpu_limit_death(-24) is False
