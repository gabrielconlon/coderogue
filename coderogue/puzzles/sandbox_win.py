"""Windows helpers for the sandbox: process-tree kill and the minimal environment.

Windows has no rlimits or cheap network namespaces, so only the timeout, the output cap and
the scrubbed environment apply there.
"""

from __future__ import annotations

import os
import shutil
import subprocess

CREATE_NEW_PROCESS_GROUP = 0x00000200
CREATE_NO_WINDOW = 0x08000000


def popen_kwargs() -> dict[str, object]:
    """Own process group (for tree kills) and no console window flashing up."""
    return {"creationflags": CREATE_NEW_PROCESS_GROUP | CREATE_NO_WINDOW}


def kill_tree(proc: subprocess.Popen[bytes]) -> None:
    """Kill ``proc`` and its children with ``taskkill /T /F``, falling back to ``kill()``."""
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
