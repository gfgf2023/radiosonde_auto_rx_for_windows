import subprocess
from pathlib import Path

from autorx.config import read_auto_rx_config


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
BUILD_SCRIPT = REPOSITORY_ROOT / "build-windows.ps1"
RELEASE_SCRIPTS = REPOSITORY_ROOT / "release" / "windows"
WINDOWS_CONFIG = REPOSITORY_ROOT / "auto_rx" / "station.cfg.example.windows"
DECODERS = {
    "dft_detect",
    "fsk_demod",
    "imet4iq",
    "mk2a1680mod",
    "rs41mod",
    "dfm09mod",
    "m10mod",
    "m20mod",
    "rs92mod",
    "lms6Xmod",
    "meisei100mod",
    "imet54mod",
    "mp3h1mod",
    "mts01mod",
    "iq_dec",
    "weathex301d",
    "rd94rd41drop",
}


def run_validation(tool_directory):
    return subprocess.run(
        [
            "powershell.exe",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(BUILD_SCRIPT),
            "-ThirdPartyBin",
            str(tool_directory),
            "-ValidateOnly",
        ],
        cwd=REPOSITORY_ROOT,
        capture_output=True,
        text=True,
    )


def test_windows_release_layout_and_config_are_complete():
    build_script = BUILD_SCRIPT.read_text(encoding="utf-8")

    assert len(DECODERS) == 17
    for decoder in DECODERS:
        assert f'"{decoder}"' in build_script
    assert "third_party/windows/bin" in build_script
    assert "Compress-Archive" in build_script

    start_script = (RELEASE_SCRIPTS / "start-auto-rx.cmd").read_text(encoding="ascii")
    diagnose_script = (RELEASE_SCRIPTS / "diagnose.cmd").read_text(encoding="ascii")
    assert "station.cfg.example.windows" in start_script
    assert "diagnose.cmd" in start_script
    for executable in ("rtl_fm.exe", "rtl_power.exe", "sox.exe"):
        assert executable in diagnose_script

    config = read_auto_rx_config(str(WINDOWS_CONFIG), no_sdr_test=True)
    assert config["sdr_type"] == "RTLSDR"
    assert config["sdr_fm"] == r"..\\bin\\rtl_fm.exe"
    assert config["sdr_power"] == r"..\\bin\\rtl_power.exe"
    config_text = WINDOWS_CONFIG.read_text(encoding="utf-8")
    assert "RTL_TCP example" in config_text
    assert "sdr_port = 1234" in config_text


def test_windows_build_validation_lists_all_missing_tools(tmp_path):
    result = run_validation(tmp_path / "not-present")
    output = result.stdout + result.stderr

    assert result.returncode != 0
    assert "Missing required third-party Windows tools" in output
    for executable in ("rtl_fm.exe", "rtl_power.exe", "sox.exe"):
        assert executable in output


def test_windows_build_validation_accepts_complete_tool_directory(tmp_path):
    for executable in ("rtl_fm.exe", "rtl_power.exe", "sox.exe"):
        (tmp_path / executable).write_bytes(b"placeholder")

    result = run_validation(tmp_path)

    assert result.returncode == 0, result.stdout + result.stderr
    assert "Validated third-party Windows tools" in result.stdout
