"""Exercise the real make/uv workflow with a tiny offline OPF wheel."""

import os
from pathlib import Path
import shutil
import subprocess
import sys
from zipfile import ZipFile


ROOT = Path(__file__).resolve().parents[1]


def test_engine_selection_survives_sync_and_cli_commands(tmp_path):
    wheel = tmp_path / "opf-0.0.0-py3-none-any.whl"
    with ZipFile(wheel, "w") as archive:
        archive.writestr("opf/__init__.py", "")
        archive.writestr("opf/_api.py", '''
from types import SimpleNamespace
class OPF:
    def __init__(self, *, device):
        pass
    def redact(self, text):
        return SimpleNamespace(to_dict=lambda: {"detected_spans": [], "redacted_text": text})
''')
        archive.writestr("opf-0.0.0.dist-info/METADATA", "Metadata-Version: 2.1\nName: opf\nVersion: 0.0.0\n")
        archive.writestr("opf-0.0.0.dist-info/WHEEL", "Wheel-Version: 1.0\nRoot-Is-Purelib: true\nTag: py3-none-any\n")
        record = "opf-0.0.0.dist-info/RECORD"
        archive.writestr(record, "\n".join(f"{name},," for name in [*archive.namelist(), record]))
    (tmp_path / "pyproject.toml").write_text(f'''
[project]
name = "engine-workflow-test"
version = "0.0.0"
requires-python = ">=3.14"
dependencies = []
[project.optional-dependencies]
opf = ["opf @ {wheel.as_uri()}"]
[tool.uv]
package = false
''')
    shutil.copy(ROOT / "Makefile", tmp_path)
    (tmp_path / "backend").mkdir()
    shutil.copy(ROOT / "backend" / "detector.py", tmp_path / "backend")
    (tmp_path / "backend" / "__init__.py").touch()
    env = {
        **os.environ,
        "UV_PYTHON": sys.executable,
        "UV_PYTHON_DOWNLOADS": "never",
        "UV_OFFLINE": "1",
        "UV_CACHE_DIR": str(tmp_path / "cache"),
        "UV_PROJECT_ENVIRONMENT": str(tmp_path / ".venv"),
    }
    env.pop("VIRTUAL_ENV", None)

    def run(*command, input=None, check=True):
        return subprocess.run(command, cwd=tmp_path, env=env, text=True, input=input,
                              capture_output=True, timeout=60, check=check)

    # A failed installation must not record OPF as enabled.
    assert run("make", "install-opf", check=False).returncode != 0
    assert not (tmp_path / ".opf-enabled").exists()
    run("uv", "lock")
    run("make", "install-opf")
    assert (tmp_path / ".opf-enabled").exists()
    assert "OpenAI Privacy Filter" in run("make", "engine").stdout
    run("make", "install")
    assert '"engine": "opf"' in run("make", "scan", input="hello").stdout
    run("make", "uninstall-opf")
    assert not (tmp_path / ".opf-enabled").exists()
    assert "Regex heuristic" in run("make", "engine").stdout
    assert '"engine": "heuristic"' in run("make", "scan", input="hello").stdout
