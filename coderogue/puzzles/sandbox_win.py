"""Windows helpers for the sandbox: Job Object, process-tree kill and the minimal environment.

Windows has no rlimits or cheap network namespaces, so only the timeout, the output cap and
the scrubbed environment apply there. Each run's process is put in a Job Object with
``JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE``: everything it spawns joins the job, and terminating
or closing the job kills the whole tree, even processes whose parent already exited. If the
Job Object cannot be created (ctypes missing, nested-job restrictions on old Windows), the
sandbox falls back to ``taskkill /T /F``. A child that spawns something in the few
microseconds before it is assigned to the job can escape it; that is accepted.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from typing import Any

CREATE_NEW_PROCESS_GROUP = 0x00000200
CREATE_NO_WINDOW = 0x08000000


def popen_kwargs() -> dict[str, object]:
    """Own process group (for tree kills) and no console window flashing up."""
    return {"creationflags": CREATE_NEW_PROCESS_GROUP | CREATE_NO_WINDOW}


JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x00002000
_JOB_OBJECT_EXTENDED_LIMIT_INFORMATION_CLASS = 9


def _kernel32() -> Any:
    import ctypes

    return ctypes.WinDLL("kernel32", use_last_error=True)  # type: ignore[attr-defined]


def _extended_limit_info(flags: int) -> Any:
    """A JOBOBJECT_EXTENDED_LIMIT_INFORMATION with ``LimitFlags`` set (other fields zero)."""
    import ctypes
    from ctypes import wintypes

    class IoCounters(ctypes.Structure):
        _fields_ = [(n, ctypes.c_ulonglong) for n in (
            "ReadOperationCount", "WriteOperationCount", "OtherOperationCount",
            "ReadTransferCount", "WriteTransferCount", "OtherTransferCount")]

    class BasicLimits(ctypes.Structure):
        _fields_ = [
            ("PerProcessUserTimeLimit", ctypes.c_longlong),
            ("PerJobUserTimeLimit", ctypes.c_longlong),
            ("LimitFlags", wintypes.DWORD),
            ("MinimumWorkingSetSize", ctypes.c_size_t),
            ("MaximumWorkingSetSize", ctypes.c_size_t),
            ("ActiveProcessLimit", wintypes.DWORD),
            ("Affinity", ctypes.c_size_t),
            ("PriorityClass", wintypes.DWORD),
            ("SchedulingClass", wintypes.DWORD),
        ]

    class ExtendedLimits(ctypes.Structure):
        _fields_ = [
            ("BasicLimitInformation", BasicLimits),
            ("IoInfo", IoCounters),
            ("ProcessMemoryLimit", ctypes.c_size_t),
            ("JobMemoryLimit", ctypes.c_size_t),
            ("PeakProcessMemoryUsed", ctypes.c_size_t),
            ("PeakJobMemoryUsed", ctypes.c_size_t),
        ]

    info = ExtendedLimits()
    info.BasicLimitInformation.LimitFlags = flags
    return info


def attach(proc: subprocess.Popen[bytes]) -> Any:
    """Put ``proc`` in a new kill-on-close Job Object; return the job handle or None."""
    try:
        import ctypes

        k32 = _kernel32()
        k32.CreateJobObjectW.restype = ctypes.c_void_p
        job = k32.CreateJobObjectW(None, None)
        if not job:
            return None
        info = _extended_limit_info(JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE)
        ok = k32.SetInformationJobObject(
            ctypes.c_void_p(job), _JOB_OBJECT_EXTENDED_LIMIT_INFORMATION_CLASS,
            ctypes.byref(info), ctypes.sizeof(info))
        handle = int(getattr(proc, "_handle", 0) or 0)
        if not ok or not handle or not k32.AssignProcessToJobObject(
                ctypes.c_void_p(job), ctypes.c_void_p(handle)):
            k32.CloseHandle(ctypes.c_void_p(job))
            return None
        return job
    except Exception:  # noqa: BLE001 - any ctypes trouble degrades to taskkill
        return None


def release(job: Any) -> None:
    """Close the job handle; with KILL_ON_JOB_CLOSE that kills anything still in it."""
    if not job:
        return
    try:
        import ctypes

        _kernel32().CloseHandle(ctypes.c_void_p(job))
    except Exception:  # noqa: BLE001
        pass


def _terminate_job(job: Any) -> bool:
    try:
        import ctypes

        return bool(_kernel32().TerminateJobObject(ctypes.c_void_p(job), 1))
    except Exception:  # noqa: BLE001
        return False


def kill_strays(marker: str, root: str) -> int:
    """Nothing to sweep: the Job Object already holds every descendant."""
    return 0


def is_cpu_limit_death(returncode: int | None) -> bool:
    """Windows has no CPU rlimit."""
    return False


def kill_tree(proc: subprocess.Popen[bytes], job: Any = None) -> None:
    """Kill ``proc`` and every descendant: terminate its Job Object when it has one, else
    ``taskkill /T /F``; ``proc.kill()`` last."""
    if job and _terminate_job(job):
        try:
            proc.kill()
        except OSError:
            pass
        return
    taskkill = shutil.which("taskkill")
    if taskkill:
        try:
            subprocess.run(
                [taskkill, "/T", "/F", "/PID", str(proc.pid)],
                capture_output=True,
                timeout=5,
                creationflags=CREATE_NO_WINDOW,
            )
        except (OSError, subprocess.SubprocessError):
            pass
    try:
        proc.kill()
    except OSError:
        pass


def base_path_dirs() -> list[str]:
    """System32 and the Windows directory: enough for interpreters to start."""
    root = os.environ.get("SYSTEMROOT", r"C:\Windows")
    return [os.path.join(root, "System32"), root]


def extra_env(tmpdir: str) -> dict[str, str]:
    """Variables Windows processes need to start at all (SYSTEMROOT, TEMP, ...)."""
    env = {
        "TEMP": tmpdir,
        "TMP": tmpdir,
        "USERPROFILE": tmpdir,
    }
    for key in ("SYSTEMROOT", "WINDIR", "COMSPEC", "PATHEXT", "SYSTEMDRIVE"):
        if key in os.environ:
            env[key] = os.environ[key]
    return env
