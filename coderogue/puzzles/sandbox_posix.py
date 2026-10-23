"""POSIX helpers for the sandbox: rlimit launcher shim, network isolation, group kill.

Resource limits are applied by a tiny launcher (:data:`RLIMIT_SHIM`) run with the game's own
Python interpreter. It calls ``resource.setrlimit`` and then ``os.execv``s the real command, so
the limits are inherited by the player's interpreter without using ``preexec_fn`` (which is
unsafe with threads). Failure to set any one limit is ignored.

Network isolation uses ``unshare -rn`` (new user + network namespace) on Linux when it is
installed and permitted. On macOS there is no supported equivalent: ``sandbox-exec`` is
deprecated and undocumented, so the MVP does not block the network there.
"""

from __future__ import annotations

import functools
import math
import os
import shutil
import signal
import subprocess
import sys

#: Limits applied by the shim, besides CPU seconds (which depend on the timeout).
FSIZE_BYTES = 8 * 1024 * 1024
NOFILE = 64
NPROC_HEADROOM = 32

# argv: shim cpu_s fsize nofile nproc_headroom target...
RLIMIT_SHIM = r"""
import os, sys
try:
    import resource
except ImportError:
    resource = None

def _count_user_procs():
    # RLIMIT_NPROC counts every process of the user, not just ours. Only Linux exposes a
    # cheap count (/proc); elsewhere the limit is skipped rather than breaking fork().
    if not sys.platform.startswith("linux"):
        return None
    uid = os.getuid()
    n = 0
    try:
        for name in os.listdir("/proc"):
            if name.isdigit():
                try:
                    if os.stat("/proc/" + name).st_uid == uid:
                        n += 1
                except OSError:
                    pass
    except OSError:
        return None
    return n

def _limit(name, value):
    if resource is None or value is None:
        return
    which = getattr(resource, name, None)
    if which is None:
        return
    try:
        soft, hard = resource.getrlimit(which)
        if hard != resource.RLIM_INFINITY:
            value = min(value, hard)
        resource.setrlimit(which, (value, hard))
    except (ValueError, OSError):
        pass

cpu, fsize, nofile, headroom = (int(a) for a in sys.argv[1:5])
_limit("RLIMIT_CPU", cpu)
_limit("RLIMIT_FSIZE", fsize)
_limit("RLIMIT_NOFILE", nofile)
procs = _count_user_procs()
_limit("RLIMIT_NPROC", None if procs is None else procs + headroom)
target = sys.argv[5:]
os.execv(target[0], target)
"""


def shim_interpreter() -> str | None:
    """A Python that can run the shim: the game's own, unless frozen without a usable one."""
    if not getattr(sys, "frozen", False):
        return sys.executable
    from coderogue.languages import get

    rt = get("python").detect()
    return rt.executable if rt else None


def rlimit_prefix(timeout_s: float) -> list[str]:
    """argv prefix that applies rlimits then execs the rest; empty if no shim is possible."""
    py = shim_interpreter()
    if not py:
        return []
    cpu = math.ceil(timeout_s) + 1  # whole seconds, rounded up, plus one
    return [py, "-I", "-S", "-B", "-c", RLIMIT_SHIM, str(cpu), str(FSIZE_BYTES), str(NOFILE),
            str(NPROC_HEADROOM)]


@functools.cache
def unshare_works() -> bool:
    """True on Linux when ``unshare -rn`` can create a network namespace here."""
    if not sys.platform.startswith("linux"):
        return False
    exe = shutil.which("unshare")
    if not exe:
        return False
    try:
        cp = subprocess.run([exe, "-rn", "true"], capture_output=True, timeout=5)
    except (OSError, subprocess.SubprocessError):
        return False
    return cp.returncode == 0


def network_prefix() -> list[str]:
    """argv prefix that cuts network access, or empty when unavailable (always on macOS)."""
    if unshare_works():
        return [shutil.which("unshare") or "unshare", "-rn"]
    return []


def popen_kwargs() -> dict[str, object]:
    """Extra ``Popen`` arguments: a new session so the whole group can be killed."""
    return {"start_new_session": True}


def kill_tree(proc: subprocess.Popen[bytes]) -> None:
    """SIGKILL the process group led by ``proc`` (no-op if it is already gone)."""
    try:
        os.killpg(proc.pid, signal.SIGKILL)
    except (ProcessLookupError, PermissionError):
        pass
    except OSError:
        try:
            proc.kill()
        except OSError:
            pass


def base_path_dirs() -> list[str]:
    """Standard binary directories for the scrubbed PATH."""
    return ["/usr/local/bin", "/usr/bin", "/bin"]


def extra_env(tmpdir: str) -> dict[str, str]:
    """Platform-specific variables beyond PATH/HOME/LANG (none on POSIX)."""
    return {}
