import sys

import pytest

import backend.detector as detector


@pytest.fixture(autouse=True)
def isolate_detector(monkeypatch):
    """Unit/API tests must never download weights or depend on an installed model."""
    monkeypatch.setitem(sys.modules, "opf", None)
    monkeypatch.setitem(sys.modules, "opf._api", None)
    monkeypatch.setattr(detector, "_detector", None)
    monkeypatch.delenv("SENTINEL_ENGINE", raising=False)
    monkeypatch.delenv("SENTINEL_PRELOAD", raising=False)
