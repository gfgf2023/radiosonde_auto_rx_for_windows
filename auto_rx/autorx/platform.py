"""Small platform-specific command helpers."""

import os
import signal
import subprocess
import sys


def is_windows():
    """Return whether auto_rx is running on Windows."""
    return sys.platform.startswith("win")


def null_device():
    """Return the shell null device for the current platform."""
    if is_windows():
        return "NUL"
    return "/dev/null"


def resolve_executable(executable):
    """Add the Windows executable suffix when it is not already present."""
    if is_windows() and not executable.lower().endswith(".exe"):
        return executable + ".exe"
    return executable


def translate_command(command):
    """Translate shell null-device references for the current platform."""
    if is_windows():
        return command.replace("/dev/null", null_device())
    return command


def run_command(command, timeout=None, **kwargs):
    """Run a shell command with platform translation and a Python timeout."""
    if isinstance(command, str):
        command = translate_command(command)
    kwargs.setdefault("shell", True)
    return subprocess.run(command, timeout=timeout, **kwargs)


def popen_kwargs():
    """Return subprocess group settings suitable for the current platform."""
    if is_windows():
        return {
            "creationflags": getattr(
                subprocess, "CREATE_NEW_PROCESS_GROUP", 0x00000200
            )
        }
    return {"preexec_fn": os.setsid}


def terminate_process_tree(process):
    """Terminate a decoder process and any children it started."""
    if process is None:
        return

    if is_windows():
        try:
            subprocess.run(
                ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                check=False,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            return
        except (OSError, subprocess.SubprocessError):
            pass

    else:
        try:
            os.killpg(os.getpgid(process.pid), signal.SIGKILL)
        except OSError:
            pass

    try:
        process.kill()
    except OSError:
        pass
