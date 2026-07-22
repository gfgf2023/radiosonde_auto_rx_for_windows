"""Small platform-specific command helpers."""

import os
import re
import signal
import subprocess
import sys


LOCAL_DECODER_EXECUTABLES = frozenset(
    (
        "dft_detect",
        "dfm09mod",
        "m10mod",
        "rs41mod",
        "rs92mod",
        "fsk_demod",
        "mk2a1680mod",
        "lms6Xmod",
        "meisei100mod",
        "imet54mod",
        "mp3h1mod",
        "m20mod",
        "imet4iq",
        "mts01mod",
        "iq_dec",
        "weathex301d",
    )
)

_LOCAL_DECODER_TOKEN = re.compile(
    r"(?<!\S)\./(?P<executable>[A-Za-z0-9_-]+)(?:\.exe)?(?=$|\s|[|;&])"
)


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
        command = command.replace("/dev/null", null_device())

        def replace_local_decoder(match):
            executable = match.group("executable")
            if executable not in LOCAL_DECODER_EXECUTABLES:
                return match.group(0)
            return ".\\" + resolve_executable(executable)

        return _LOCAL_DECODER_TOKEN.sub(replace_local_decoder, command)
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
