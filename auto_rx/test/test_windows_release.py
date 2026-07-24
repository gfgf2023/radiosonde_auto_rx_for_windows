import subprocess
import zipfile
from pathlib import Path

from autorx import config as autorx_config
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
    "m10m20mod",
    "rs92mod",
    "lms6Xmod",
    "meisei100mod",
    "imet54mod",
    "mp3h1mod",
    "mts01mod",
    "cf06ht03mod",
    "c50iq",
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


def run_application_staging(source_root, release_root):
    return subprocess.run(
        [
            "powershell.exe",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(BUILD_SCRIPT),
            "-SourceRoot",
            str(source_root),
            "-ReleaseRoot",
            str(release_root),
            "-Version",
            "privacy-test",
            "-StageApplicationOnly",
        ],
        cwd=REPOSITORY_ROOT,
        capture_output=True,
        text=True,
    )


def test_windows_release_layout_and_config_are_complete():
    build_script = BUILD_SCRIPT.read_text(encoding="utf-8")

    assert len(DECODERS) == 18
    for decoder in DECODERS:
        assert f'"{decoder}"' in build_script
    assert "third_party/windows/bin" in build_script
    assert "Compress-Archive" in build_script

    start_script = (RELEASE_SCRIPTS / "start-auto-rx.cmd").read_text(encoding="ascii")
    diagnose_script = (RELEASE_SCRIPTS / "diagnose.cmd").read_text(encoding="ascii")
    assert "station.cfg.example.windows" in start_script
    assert "diagnose.cmd" in start_script
    for executable in ("rtl_fm.exe", "rtl_power.exe", "rtl_sdr.exe", "sox.exe"):
        assert executable in diagnose_script
    for required_dll in ("rtlsdr.dll", "libusb-1.0.dll"):
        assert required_dll in diagnose_script
    assert "py -3 --version" in diagnose_script
    assert "py -3 --version" in start_script
    assert "Failed to create" in start_script
    assert "Failed to install auto_rx requirements" in start_script

    config = read_auto_rx_config(str(WINDOWS_CONFIG), no_sdr_test=True)
    assert config["sdr_type"] == "RTLSDR"
    assert config["sdr_fm"] == r"..\\bin\\rtl_fm.exe"
    assert config["sdr_power"] == r"..\\bin\\rtl_power.exe"
    config_text = WINDOWS_CONFIG.read_text(encoding="utf-8")
    assert "RTL_TCP example" in config_text
    assert "sdr_port = 1234" in config_text


def test_windows_default_rtlsdr_config_requires_rtl_sdr_without_hardware(monkeypatch):
    monkeypatch.setattr(
        autorx_config.autorx_platform, "executable_exists", lambda executable: False
    )
    monkeypatch.setattr(
        autorx_config, "test_sdr", lambda **kwargs: (_ for _ in ()).throw(
            AssertionError("RTL-SDR must not be probed when rtl_sdr is missing")
        )
    )

    assert read_auto_rx_config(str(WINDOWS_CONFIG)) is None


def test_windows_build_validation_lists_all_missing_tools(tmp_path):
    result = run_validation(tmp_path / "not-present")
    output = result.stdout + result.stderr

    assert result.returncode != 0
    assert "Missing required third-party Windows files" in output
    for required_file in (
        "rtl_fm.exe",
        "rtl_power.exe",
        "rtl_sdr.exe",
        "sox.exe",
        "rtlsdr.dll",
        "libusb-1.0.dll",
    ):
        assert required_file in output


def test_windows_build_validation_accepts_complete_tool_directory(tmp_path):
    for required_file in (
        "rtl_fm.exe",
        "rtl_power.exe",
        "rtl_sdr.exe",
        "sox.exe",
        "rtlsdr.dll",
        "libusb-1.0.dll",
    ):
        (tmp_path / required_file).write_bytes(b"placeholder")

    result = run_validation(tmp_path)

    assert result.returncode == 0, result.stdout + result.stderr
    assert "Validated third-party Windows tools" in result.stdout


def test_windows_application_staging_excludes_local_runtime_data(tmp_path):
    source_root = tmp_path / "source"
    application = source_root / "auto_rx"
    sentinel = "station-secret-must-not-be-packaged"
    tracked_files = {
        "auto_rx/auto_rx.py": "print('auto_rx')\n",
        "auto_rx/autorx/__init__.py": "__version__ = 'test'\n",
        "auto_rx/autorx/static/site.css": "body {}\n",
        "auto_rx/utils/log_to_kml.py": "print('utility')\n",
        "auto_rx/log/log_files_go_here.txt": "",
        "auto_rx/requirements.txt": "flask\n",
        "auto_rx/station.cfg.example.windows": "sdr_type = RTLSDR\n",
    }
    for relative_path, contents in tracked_files.items():
        path = source_root / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(contents, encoding="utf-8")

    # These are deliberately untracked local artifacts that a release must not leak.
    runtime_files = {
        "station.cfg": f"aprs_user = {sentinel}\n",
        "log/receiver.log": sentinel,
        "log/tracked-log.txt": sentinel,
        "logs/power.log": sentinel,
        ".venv/pyvenv.cfg": sentinel,
        "__pycache__/auto_rx.cpython-312.pyc": sentinel,
    }
    for relative_path, contents in runtime_files.items():
        path = application / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(contents, encoding="utf-8")

    subprocess.run(["git", "init", "-q"], cwd=source_root, check=True)
    subprocess.run(["git", "add", *tracked_files], cwd=source_root, check=True)

    release_root = tmp_path / "release"
    result = run_application_staging(source_root, release_root)
    assert result.returncode == 0, result.stdout + result.stderr

    staged_application = release_root / "auto_rx-windows-privacy-test" / "auto_rx"
    archive_path = release_root / "auto_rx-windows-privacy-test.zip"
    assert (staged_application / "station.cfg.example.windows").is_file()
    assert (staged_application / "log" / "log_files_go_here.txt").is_file()
    assert (staged_application / "log" / "log_files_go_here.txt").read_text(encoding="utf-8") == ""
    assert not (staged_application / "station.cfg").exists()
    assert sentinel not in "\n".join(
        path.read_text(encoding="utf-8", errors="ignore")
        for path in staged_application.rglob("*")
        if path.is_file()
    )

    with zipfile.ZipFile(archive_path) as archive:
        archive_contents = "\n".join(
            archive.read(name).decode("utf-8", errors="ignore")
            for name in archive.namelist()
            if not name.endswith("/")
        )
        archive_names = set(archive.namelist())

    assert sentinel not in archive_contents
    assert any(name.endswith("auto_rx/station.cfg.example.windows") for name in archive_names)
    assert any(name.endswith("auto_rx/log/log_files_go_here.txt") for name in archive_names)
    assert not any(name.endswith("auto_rx/station.cfg") for name in archive_names)
    assert not any(name.endswith("auto_rx/log/tracked-log.txt") for name in archive_names)
