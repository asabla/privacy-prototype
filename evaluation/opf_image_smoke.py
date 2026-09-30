"""Check the CPU image and fail-closed startup without downloading model assets."""

import argparse
import subprocess


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image", default="sentinel-opf:ci")
    args = parser.parse_args()
    base = ["docker", "run", "--rm", "--network", "none", "--read-only", args.image]
    subprocess.run([*base, "python", "-c", "import torch,opf; "
                    "assert torch.version.cuda is None; assert torch.__version__ == '2.14.0+cpu'"],
                   check=True, timeout=60)
    result = subprocess.run(base, capture_output=True, text=True, timeout=30)
    assert result.returncode == 1 and "Model assets are missing or do not match pinned checksums" in result.stderr
    print("CPU-only OPF imports passed; missing assets prevented offline startup")


if __name__ == "__main__":
    main()
