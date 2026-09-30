"""Provision public, pinned OPF assets; verify them without network before serving."""

import argparse
from dataclasses import dataclass
import hashlib
import os
from pathlib import Path
import sys
import tempfile
from urllib.request import urlopen


REVISION = "7ffa9a043d54d1be65afb281eddf0ffbe629385b"
CHECKPOINT_URL = f"https://huggingface.co/openai/privacy-filter/resolve/{REVISION}/original/"
TOKENIZER_URL = "https://openaipublic.blob.core.windows.net/encodings/o200k_base.tiktoken"


@dataclass(frozen=True)
class Asset:
    path: str
    url: str
    size: int
    sha256: str


ASSETS = (
    Asset("checkpoint/original/config.json", CHECKPOINT_URL + "config.json", 707,
          "048a20604a3622de208d30df57cd5424bb583639b9ba20ddd7da593d3f89a248"),
    Asset("checkpoint/original/dtypes.json", CHECKPOINT_URL + "dtypes.json", 4108,
          "e936acb3d039b35ec55438af2fffd424a53c7685b895775c186b26c7df79fcc7"),
    Asset("checkpoint/original/model.safetensors", CHECKPOINT_URL + "model.safetensors", 2798984088,
          "9c262cbe68a0c8a50590a648ef8341a2b7d3be1fa11dfb79893fe0b03ce57b5c"),
    Asset("checkpoint/original/viterbi_calibration.json", CHECKPOINT_URL + "viterbi_calibration.json", 372,
          "bbc8611ef08a55ed72d64856cbbbb9a91db8dfa881f0a92e2afbad6e4bbc775a"),
    Asset("tokenizer-cache/fb374d419588a4632f3f557e76b4b70aebbca790", TOKENIZER_URL, 3613922,
          "446a9538cb6c348e3516120d7c08b09f57c36495e2acfffe59a5bf8b0cfb1a2d"),
)


def verify_asset(path: Path, asset: Asset):
    if not path.is_file() or path.stat().st_size != asset.size:
        raise ValueError(f"Missing or invalid model asset: {asset.path}")
    with path.open("rb") as stream:
        digest = hashlib.file_digest(stream, "sha256").hexdigest()
    if digest != asset.sha256:
        raise ValueError(f"Model checksum mismatch: {asset.path}")


def verify(directory: Path):
    for asset in ASSETS:
        verify_asset(directory / asset.path, asset)


def provision(directory: Path):
    for asset in ASSETS:
        path = directory / asset.path
        if path.exists():
            verify_asset(path, asset)
            continue
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(dir=path.parent, prefix=".download-", delete=False) as out:
                temporary = Path(out.name)
                with urlopen(asset.url, timeout=60) as response:
                    size = 0
                    while chunk := response.read(1024 * 1024):
                        size += len(chunk)
                        if size > asset.size:
                            raise ValueError(f"Model download exceeded expected size: {asset.path}")
                        out.write(chunk)
            verify_asset(temporary, asset)
            temporary.chmod(0o644)
            temporary.replace(path)
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
    verify(directory)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", type=Path, default=Path(os.environ.get("OPF_ASSETS_DIR", "/models")))
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--download", action="store_true", help="Download only missing public assets during setup")
    mode.add_argument("--serve", action="store_true", help="Verify offline, then start the real-model service")
    args = parser.parse_args()
    try:
        if args.download:
            provision(args.directory)
        else:
            verify(args.directory)
    except (OSError, ValueError):
        sys.exit("Model assets are missing or do not match pinned checksums. Run the documented provisioning check.")
    if args.serve:
        os.environ.update(SENTINEL_ENGINE="opf", SENTINEL_PRELOAD="1", OPF_DEVICE="cpu",
                          OPF_CHECKPOINT=str(args.directory / "checkpoint/original"),
                          TIKTOKEN_CACHE_DIR=str(args.directory / "tokenizer-cache"),
                          HF_HUB_OFFLINE="1", HF_HUB_DISABLE_IMPLICIT_TOKEN="1", HF_HUB_DISABLE_TELEMETRY="1")
        os.execv(sys.executable, [sys.executable, "-m", "uvicorn", "backend.main:app", "--host", "0.0.0.0",
                 "--port", "8000", "--no-access-log", "--no-proxy-headers", "--limit-concurrency", "16",
                 "--timeout-graceful-shutdown", "30"])
    print(f"Verified {len(ASSETS)} model assets at revision {REVISION}")


if __name__ == "__main__":
    main()
