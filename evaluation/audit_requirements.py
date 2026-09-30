"""Map CPU wheel versions to their upstream release for registry advisory queries.

Use only with pip-audit --disable-pip: this is not an installation requirements file.
The wheel hashes stay intact; uv.lock remains the installation source of truth.
"""

from pathlib import Path
import re
import sys


def registry_versions(text: str) -> str:
    # PyPI has advisories for torch 2.x.y, but no torch 2.x.y+cpu registry record.
    return re.sub(r"(?m)^(torch==\d+\.\d+\.\d+)\+cpu(?=[ ;\\\r\n]|$)", r"\1", text)


if __name__ == "__main__":
    path = Path(sys.argv[1])
    path.write_text(registry_versions(path.read_text()))
