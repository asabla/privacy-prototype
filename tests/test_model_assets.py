from io import BytesIO
import hashlib

import pytest

from ops import model_assets
from evaluation.audit_requirements import registry_versions


@pytest.fixture
def asset(monkeypatch):
    item = model_assets.Asset("checkpoint/test.bin", "https://example.org/public-model", 4,
                              hashlib.sha256(b"data").hexdigest())
    monkeypatch.setattr(model_assets, "ASSETS", (item,))
    return item


def test_provision_downloads_once_and_verification_never_uses_network(tmp_path, monkeypatch, asset):
    monkeypatch.setattr(model_assets, "urlopen", lambda *a, **k: BytesIO(b"data"))
    model_assets.provision(tmp_path)

    def no_network(*args, **kwargs):
        raise AssertionError("Verification must not connect")

    monkeypatch.setattr(model_assets, "urlopen", no_network)
    model_assets.verify(tmp_path)
    model_assets.provision(tmp_path)
    assert (tmp_path / asset.path).read_bytes() == b"data"


@pytest.mark.parametrize("body", [b"bad", b"oops", b"too long"])
def test_failed_download_leaves_no_usable_or_partial_asset(tmp_path, monkeypatch, asset, body):
    monkeypatch.setattr(model_assets, "urlopen", lambda *a, **k: BytesIO(body))
    with pytest.raises(ValueError):
        model_assets.provision(tmp_path)
    assert list(tmp_path.rglob("*.bin")) == []
    assert list(tmp_path.rglob(".download-*")) == []


def test_existing_corrupt_asset_is_rejected_without_overwrite(tmp_path, monkeypatch, asset):
    path = tmp_path / asset.path
    path.parent.mkdir(parents=True)
    path.write_bytes(b"oops")
    monkeypatch.setattr(model_assets, "urlopen", lambda *a, **k: pytest.fail("Must not replace existing assets"))
    with pytest.raises(ValueError, match="checksum"):
        model_assets.provision(tmp_path)
    assert path.read_bytes() == b"oops"


def test_missing_assets_prevent_serve_before_exec(tmp_path, monkeypatch, asset):
    monkeypatch.setattr("sys.argv", ["assets", "--directory", str(tmp_path), "--serve"])
    monkeypatch.setattr(model_assets.os, "execv", lambda *a: pytest.fail("Must not start with missing assets"))
    with pytest.raises(SystemExit, match="Model assets are missing"):
        model_assets.main()


def test_cpu_advisory_lookup_preserves_markers_hashes_and_other_packages():
    requirement = "torch==2.14.0+cpu ; sys_platform == 'linux' \\\n    --hash=sha256:example\nother==2.14.0+cpu\n"
    assert registry_versions(requirement) == requirement.replace("torch==2.14.0+cpu", "torch==2.14.0")
    assert registry_versions("torch==2.14.0+cpu.custom\n") == "torch==2.14.0+cpu.custom\n"
