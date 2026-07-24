"""Small platform-specific command helpers."""

import os
import re
import shlex
import signal
import shutil
import subprocess
import sys
from pathlib import Path


LOCAL_DECODER_EXECUTABLES = frozenset(
    (
        "dft_detect",
        "dfm09mod",
        "m10m20mod",
        "rs41mod",
        "rs92mod",
        "fsk_demod",
        "mk2a1680mod",
        "lms6Xmod",
        "meisei100mod",
        "imet54mod",
        "mp3h1mod",
        "imet4iq",
        "mts01mod",
        "cf06ht03mod",
        "c50iq",
        "rd94rd41drop",
        "iq_dec",
        "weathex301d",
    )
)

_LOCAL_DECODER_TOKEN = re.compile(
    r"(?<!\S)\./(?P<executable>[A-Za-z0-9_-]+)(?:\.exe)?(?=$|\s|[|;&])"
)
_CMD_METACHARACTERS = frozenset("&|<>()^\"")
_CMD_ENVIRONMENT_EXPANSION = re.compile(r"%[^%]+%")
_DEBUG_TEE_STAGE = re.compile(r"(?<!\S)tee\s+.+?\s+\|")


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


def find_executable(executable):
    """Find an executable in the working directory, release bin directory, or PATH.

    Windows releases launch Python from ``auto_rx`` while the native decoders
    and RTL-SDR tools live in the sibling ``bin`` directory.  Check that
    release layout explicitly before falling back to PATH, so running
    ``auto_rx.py`` directly from an extracted release works too.
    """
    executable = resolve_executable(executable)
    if not is_windows():
        return shutil.which(executable) or executable

    working_directory = Path.cwd()
    candidates = (
        working_directory / executable,
        working_directory.parent / "bin" / executable,
    )
    for candidate in candidates:
        if candidate.is_file():
            return str(candidate.resolve())

    return shutil.which(executable) or executable


def executable_exists(executable):
    """Return whether an executable can be located without invoking it."""
    resolved = find_executable(executable)
    return os.path.isfile(resolved) or shutil.which(resolved) is not None


def translate_command(command):
    """Translate shell null-device references for the current platform."""
    if is_windows():
        command = command.replace("/dev/null", null_device())

        def replace_local_decoder(match):
            executable = match.group("executable")
            if executable not in LOCAL_DECODER_EXECUTABLES:
                return match.group(0)
            return quote_command_argument(find_executable(executable))

        return _LOCAL_DECODER_TOKEN.sub(replace_local_decoder, command)
    return command


def prepare_shell_command(command):
    """Translate and validate a command that will be executed by a shell."""
    if not is_windows():
        return command

    if isinstance(command, str):
        if _CMD_ENVIRONMENT_EXPANSION.search(command):
            raise ValueError("Windows CMD commands containing percent signs are not supported.")
        command = _DEBUG_TEE_STAGE.sub("", command)
        return translate_command(command)

    if isinstance(command, (list, tuple)):
        if any(
            isinstance(part, str) and _CMD_ENVIRONMENT_EXPANSION.search(part)
            for part in command
        ):
            raise ValueError("Windows CMD commands containing percent signs are not supported.")
        prepared = [
            translate_command(part) if isinstance(part, str) else part
            for part in command
        ]
        return tuple(prepared) if isinstance(command, tuple) else prepared

    return command


def quote_command_argument(argument):
    """Quote one shell argument using the conventions of the active platform."""
    if is_windows():
        if _CMD_ENVIRONMENT_EXPANSION.search(argument):
            raise ValueError("Windows CMD arguments containing percent signs are not supported.")
        if any(
            character.isspace() or character in _CMD_METACHARACTERS
            for character in argument
        ):
            escaped = subprocess.list2cmdline([argument])
            if escaped.startswith('"') and escaped.endswith('"'):
                return escaped
            return '"' + escaped + '"'
        return argument
    return shlex.quote(argument)


def run_command(command, timeout=None, **kwargs):
    """Run a shell command with platform translation and tree-safe timeouts."""
    input_data = kwargs.pop("input", None)
    capture_output = kwargs.pop("capture_output", False)
    check = kwargs.pop("check", False)

    if input_data is not None:
        if kwargs.get("stdin") is not None:
            raise ValueError("stdin and input arguments may not both be used.")
        kwargs["stdin"] = subprocess.PIPE

    if capture_output:
        if kwargs.get("stdout") is not None or kwargs.get("stderr") is not None:
            raise ValueError("stdout and stderr arguments may not be used with capture_output.")
        kwargs["stdout"] = subprocess.PIPE
        kwargs["stderr"] = subprocess.PIPE

    kwargs.setdefault("shell", True)
    if kwargs["shell"]:
        command = prepare_shell_command(command)
    elif isinstance(command, str):
        command = translate_command(command)
    kwargs.update(popen_kwargs())

    with subprocess.Popen(command, **kwargs) as process:
        try:
            stdout, stderr = process.communicate(input_data, timeout=timeout)
        except subprocess.TimeoutExpired as exc:
            terminate_process_tree(process)
            stdout, stderr = process.communicate()
            exc.output = stdout
            exc.stderr = stderr
            raise

        returncode = process.poll()
        if check and returncode:
            raise subprocess.CalledProcessError(
                returncode, command, output=stdout, stderr=stderr
            )

    return subprocess.CompletedProcess(command, returncode, stdout, stderr)


def popen_kwargs():
    """Return subprocess group settings suitable for the current platform."""
    if is_windows():
        return {
            "creationflags": getattr(
                subprocess, "CREATE_NEW_PROCESS_GROUP", 0x00000200
            )
        }
    return {"start_new_session": True}


def terminate_process_tree(process):
    """Terminate a decoder process and any children it started."""
    if process is None:
        return

    if is_windows():
        try:
            result = subprocess.run(
                ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                check=False,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            if result.returncode == 0:
                return
        except (OSError, subprocess.SubprocessError):
            pass

        try:
            process.kill()
        except OSError:
            pass
        try:
            process.wait()
        except (OSError, subprocess.SubprocessError):
            pass
        return

    else:
        try:
            os.killpg(os.getpgid(process.pid), signal.SIGKILL)
        except OSError:
            pass

    try:
        process.kill()
    except OSError:
        pass
