"""Small platform-specific command helpers."""

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
