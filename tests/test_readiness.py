import secrets

import pytest
from fastapi.testclient import TestClient

from backend.detector import Detector, get_detector
from backend.main import create_app
from backend.security import Settings


def test_readiness_requires_nonempty_inference_and_recovers_after_failure(monkeypatch):
    settings = Settings(api_key=secrets.token_urlsafe(32))
    with TestClient(create_app(settings), base_url="http://127.0.0.1", headers={
        "Authorization": f"Bearer {settings.api_key}",
    }) as client:
        assert client.get("/health").status_code == 200
        assert client.get("/ready").status_code == 503
        client.post("/api/scan", json={"text": ""}).raise_for_status()
        assert client.get("/ready").status_code == 503
        client.post("/api/scan", json={"text": "alice@example.com"}).raise_for_status()
        ready = client.get("/ready")
        assert ready.json() == {"status": "ready", "engine": "heuristic"}
        assert ready.headers["cache-control"] == "no-store"
        with monkeypatch.context() as patch:
            def fail(_):
                raise RuntimeError("private-sentinel-in-error")
            patch.setattr(get_detector(), "_detect_heuristic", fail)
            response = client.post("/api/scan", json={"text": "synthetic input"})
            assert response.status_code == 503
            assert "private-sentinel" not in response.text
        assert client.get("/ready").status_code == 503
        client.post("/api/scan", json={"text": "recovered"}).raise_for_status()
        assert client.get("/ready").status_code == 200


def test_preload_finishes_before_serving():
    with TestClient(create_app(Settings(preload=True)), base_url="http://127.0.0.1") as client:
        assert client.get("/ready").json() == {"status": "ready", "engine": "heuristic"}


def test_failed_preload_stops_startup_without_exception_values(monkeypatch, caplog):
    def fail(_, text):
        raise RuntimeError("private-sentinel-startup")
    monkeypatch.setattr(Detector, "detect", fail)
    with pytest.raises(RuntimeError, match="Detector startup failed") as error:
        with TestClient(create_app(Settings(preload=True)), base_url="http://127.0.0.1"):
            pytest.fail("Failed startup must not serve requests")
    assert "private-sentinel" not in str(error.value) + caplog.text
    assert error.value.__suppress_context__ is True


def test_engine_environment_is_explicit_and_never_silently_downgrades(monkeypatch):
    monkeypatch.setenv("SENTINEL_ENGINE", "heuristic")
    assert Detector().engine == "heuristic"
    monkeypatch.setenv("SENTINEL_ENGINE", "opf")
    with pytest.raises(RuntimeError, match="OPF is required"):
        Detector()
    monkeypatch.setenv("SENTINEL_ENGINE", "private-sentinel-invalid")
    with pytest.raises(ValueError) as error:
        Detector()
    assert "private-sentinel" not in str(error.value)
    assert Detector("heuristic").engine == "heuristic"


@pytest.mark.parametrize("value,expected", [("0", False), ("1", True)])
def test_preload_environment(monkeypatch, value, expected):
    monkeypatch.setenv("SENTINEL_PRELOAD", value)
    assert Settings.from_env().preload is expected


def test_invalid_preload_configuration_is_rejected(monkeypatch):
    monkeypatch.setenv("SENTINEL_PRELOAD", "private-sentinel-invalid")
    with pytest.raises(ValueError) as error:
        Settings.from_env()
    assert "private-sentinel" not in str(error.value)
