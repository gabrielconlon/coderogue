"""POSIX helpers for the sandbox: rlimit launcher shim, network isolation, group kill.

Resource limits are applied by a tiny launcher (:data:`RLIMIT_SHIM`) run with the game's own
Python interpreter. It calls ``resource.setrlimit`` and then ``os.execv``s the real command, so
the limits are inherited by the player's interpreter without using ``preexec_fn`` (which is
unsafe with threads). Failure to set any one limit is ignored.

Network isolation uses ``unshare -rn`` (new user + network namespace) on Linux when it is
installed and permitted. On macOS there is no supported equivalent: ``sandbox-exec`` is
deprecated and undocumented, so the MVP does not block the network there.

Strays (processes that left the run's process group with ``setsid`` and keep its pipes open)
are found by :func:`stray_pids` and killed by :func:`kill_strays`.
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
#: Linux counts RLIMIT_NPROC in *threads* (tasks) across all of the user's processes, so the
#: cap is "threads the user already runs" + this headroom, and never below NPROC_FLOOR. A busy
#: desktop runs thousands of threads; a smaller cap would make every fork fail. The cap only
#: stops a runaway fork loop; the wall-clock kill is the real backstop.
NPROC_HEADROOM = 256
NPROC_FLOOR = 1024

# argv: shim cpu_s fsize nofile nproc_headroom nproc_floor target...
RLIMIT_SHIM = r"""
import os, sys
try:
    import resource
except ImportError:
    resource = None

def _count_user_threads(proc_root="/proc", uid=None, platform=sys.platform):
    # RLIMIT_NPROC counts every thread (task) of the user, not processes and not just ours.
    # Only Linux exposes a cheap count (/proc/<pid>/task); elsewhere the limit is skipped
    # rather than breaking fork().
    if not platform.startswith("linux"):
        return None
    if uid is None:
        uid = os.getuid()
    n = 0
    try:
        names = os.listdir(proc_root)
    except OSError:
        return None
    for name in names:
        if not name.isdigit():
            continue
        base = proc_root + "/" + name
        try:
            if os.stat(base).st_uid != uid:
                continue
            n += len(os.listdir(base + "/task"))
        except OSError:
            n += 1
    return n

def _nproc_limit(threads, headroom, floor):
    if threads is None:
        return None
    return max(threads + headroom, floor)

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

if __name__ == "__main__":
    cpu, fsize, nofile, headroom, floor = (int(a) for a in sys.argv[1:6])
    _limit("RLIMIT_CPU", cpu)
    _limit("RLIMIT_FSIZE", fsize)
    _limit("RLIMIT_NOFILE", nofile)
    _limit("RLIMIT_NPROC", _nproc_limit(_count_user_threads(), headroom, floor))
    target = sys.argv[6:]
    os.execv(target[0], target)
"""


def shim_interpreter() -> str | None:
    """A Python that can run the shim: the game's own, unless frozen without a usable one."""
    if not getattr(sys, "frozen", False):
        return sys.executable
    from coderogue.languages import get

    rt = get("python").detect()
    return rt.executable if rt else None


def cpu_seconds(budget_s: float) -> int:
    """RLIMIT_CPU for a run whose wall-clock budget is ``budget_s`` (timeout + start-up).

    One second above the wall limit, so a busy loop is stopped by the wall-clock kill (and
    reported as a timeout) rather than by SIGXCPU.
    """
    return math.ceil(budget_s) + 1


def rlimit_prefix(budget_s: float, nofile: int | None = None) -> list[str]:
    """argv prefix that applies rlimits then execs the rest; empty if no shim is possible.

    ``budget_s`` is the wall-clock budget (timeout plus the language's start-up allowance).
    """
    py = shim_interpreter()
    if not py:
        return []
    return [py, "-I", "-S", "-B", "-c", RLIMIT_SHIM, str(cpu_seconds(budget_s)),
            str(FSIZE_BYTES), str(nofile or NOFILE), str(NPROC_HEADROOM), str(NPROC_FLOOR)]


def is_cpu_limit_death(returncode: int | None) -> bool:
    """True when the process was killed by SIGXCPU (it ran out of CPU seconds)."""
    sig = getattr(signal, "SIGXCPU", None)
    return sig is not None and returncode == -int(sig)


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


def attach(proc: subprocess.Popen[bytes]) -> None:
    """Windows puts the child in a Job Object here; POSIX uses the process group instead."""
    return None


def release(job: object) -> None:
    """Counterpart of :func:`attach` (nothing to release on POSIX)."""


def kill_tree(proc: subprocess.Popen[bytes], job: object = None) -> None:
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


def _under(path: str, root: str) -> bool:
    return path == root or path.startswith(root.rstrip("/") + "/")


def _stray_pids_linux(needle: bytes, root: str) -> list[int]:
    pids = []
    uid = os.getuid()
    try:
        names = os.listdir("/proc")
    except OSError:
        return []
    for name in names:
        if not name.isdigit():
            continue
        base = f"/proc/{name}"
        try:
            if os.stat(base).st_uid != uid:
                continue
        except OSError:
            continue
        try:
            with open(base + "/environ", "rb") as fh:
                if needle in fh.read().split(b"\0"):
                    pids.append(int(name))
                    continue
        except OSError:
            pass
        try:
            if _under(os.readlink(base + "/cwd"), root):
                pids.append(int(name))
        except OSError:
            pass
    return pids


#: libproc ``PROC_PIDVNODEPATHINFO`` and the layout of ``struct proc_vnodepathinfo``: the
#: cwd's ``vnode_info`` (152 bytes) then its path (MAXPATHLEN), then the same for the root.
_PROC_PIDVNODEPATHINFO = 9
_VNODE_INFO_SIZE = 152
_MAXPATHLEN = 1024
_VNODEPATHINFO_SIZE = 2 * (_VNODE_INFO_SIZE + _MAXPATHLEN)


def _stray_pids_darwin(root: str) -> list[int]:
    # macOS hides other processes' environments, so strays are found by working directory
    # (libproc). A stray that chdir'd out of the sandbox is not found.
    try:
        import ctypes

        lib = ctypes.CDLL("/usr/lib/libproc.dylib")
        n = lib.proc_listallpids(None, 0)
        if n <= 0:
            return []
        pid_buf = (ctypes.c_int * (n + 256))()
        n = lib.proc_listallpids(pid_buf, ctypes.sizeof(pid_buf))
        info = ctypes.create_string_buffer(_VNODEPATHINFO_SIZE)
        pids = []
        for pid in pid_buf[: max(n, 0)]:
            got = lib.proc_pidinfo(pid, _PROC_PIDVNODEPATHINFO, ctypes.c_uint64(0), info,
                                   _VNODEPATHINFO_SIZE)
            if got < _VNODE_INFO_SIZE + _MAXPATHLEN:
                continue
            raw = info.raw[_VNODE_INFO_SIZE:_VNODE_INFO_SIZE + _MAXPATHLEN]
            cwd = raw.split(b"\0", 1)[0].decode("utf-8", "replace")
            if cwd and _under(cwd, root):
                pids.append(int(pid))
        return pids
    except Exception:  # noqa: BLE001 - best effort only
        return []


def stray_pids(marker: str, root: str) -> list[int]:
    """PIDs of this user's processes that belong to a run: their environment holds
    ``marker`` (``"NAME=value"``, Linux only) or their working directory is under ``root``."""
    root = os.path.realpath(root)
    if sys.platform.startswith("linux"):
        pids = _stray_pids_linux(marker.encode(), root)
    elif sys.platform == "darwin":
        pids = _stray_pids_darwin(root)
    else:
        pids = []
    me = os.getpid()
    return sorted({p for p in pids if p != me})


def kill_strays(marker: str, root: str) -> int:
    """SIGKILL processes of one run that escaped its process group (e.g. via ``setsid``).

    Found by the run's environment tag ``marker`` (``"CODEROGUE_RUN=<uuid>"``, Linux) or by a
    working directory inside the run's temp dir ``root``. A process that scrubbed its
    environment and left the directory is not found (this guards against mistakes, it is not
    a security boundary). Returns how many were signalled.
    """
    n = 0
    for pid in stray_pids(marker, root):
        try:
            os.kill(pid, signal.SIGKILL)
            n += 1
        except OSError:
            pass
    return n


def base_path_dirs() -> list[str]:
    """Standard binary directories for the scrubbed PATH."""
    return ["/usr/local/bin", "/usr/bin", "/bin"]


def extra_env(tmpdir: str) -> dict[str, str]:
    """Platform-specific variables beyond PATH/HOME/LANG (none on POSIX)."""
    return {}
