import importlib.util
from pathlib import Path
from queue import Queue

import pytest

import autorx
from autorx import config, web


AUTO_RX_ROOT = Path(__file__).resolve().parents[1]


def test_web_start_decoder_rejects_non_finite_frequency(monkeypatch):
    monkeypatch.setattr(config, "global_config", {"web_control": True})
    monkeypatch.setattr(config, "web_password", "secret")
    monkeypatch.setattr(autorx, "scan_results", Queue())

    with web.app.test_client() as client:
        response = client.post(
            "/start_decoder",
            data={"type": "CF6GTH", "freq": "nan", "password": "secret"},
        )

    assert response.status_code == 400
    assert autorx.scan_results.empty()


@pytest.mark.parametrize("frequency", [float("nan"), float("inf"), -1])
def test_start_decoder_ignores_invalid_frequency_before_allocating_sdr(
    monkeypatch, frequency
):
    spec = importlib.util.spec_from_file_location("auto_rx_entrypoint", AUTO_RX_ROOT / "auto_rx.py")
    entrypoint = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(entrypoint)

    monkeypatch.setattr(
        entrypoint,
        "allocate_sdr",
        lambda **kwargs: pytest.fail("invalid frequency must not allocate an SDR"),
    )

    entrypoint.start_decoder(frequency, "CF6GTH")
