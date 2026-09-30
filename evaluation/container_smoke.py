"""Build and exercise the actual Compose service using only synthetic data."""

import argparse
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
import secrets
import subprocess
import time
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--opf", action="store_true", help="Require provisioned real OPF assets via OPF_ASSETS_DIR")
    args = parser.parse_args()
    engine = "opf" if args.opf else "heuristic"
    if args.opf:
        from ops.model_assets import verify
        assets = Path(os.environ["OPF_ASSETS_DIR"]).resolve()
        verify(assets)
    key = secrets.token_urlsafe(32)
    env = {**os.environ, "SENTINEL_API_KEY": key, "PORT": "0"}
    project = "sentinel-check-" + secrets.token_hex(4)
    compose = ["docker", "compose", "--project-name", project, "--file", str(ROOT / "compose.yaml")]
    if args.opf:
        env["OPF_ASSETS_DIR"] = str(assets)
        compose += ["--file", str(ROOT / "compose.opf.yaml")]

    def run(*args):
        # Do not print expanded Compose environment or Docker inspection payloads.
        result = subprocess.run(args, cwd=ROOT, env=env, text=True, capture_output=True, timeout=600)
        if result.returncode:
            diagnostic = (result.stderr + result.stdout).replace(key, "[OPERATOR_KEY]")[-8000:]
            raise RuntimeError(f"Container command failed: {args[0]} (exit {result.returncode})\n{diagnostic}")
        return result.stdout.strip()

    try:
        print("Building and starting the isolated reference container", flush=True)
        run(*compose, "up", "--build", "--detach", "--wait", "--wait-timeout", "180")
        container = run(*compose, "ps", "--quiet", "sentinel")
        info = json.loads(run("docker", "inspect", container))[0]
        config, host = info["Config"], info["HostConfig"]
        assert config["User"] == "10001:10001", "Container must not run as root"
        assert host["ReadonlyRootfs"] and host["CapDrop"] == ["ALL"]
        assert "no-new-privileges:true" in host["SecurityOpt"]
        assert host["Memory"] == (8192 if args.opf else 512) * 1024 * 1024
        assert host["PidsLimit"] == (128 if args.opf else 64)
        mounts = info["Mounts"]
        if args.opf:
            models = [mount for mount in mounts if mount["Destination"] == "/models"]
            assert len(models) == 1 and models[0]["Type"] == "bind" and not models[0]["RW"]
            mounts = [mount for mount in mounts if mount["Destination"] != "/models"]
            run("docker", "exec", container, "python", "-c",
                "import torch; assert torch.version.cuda is None; assert torch.__version__ == '2.14.0+cpu'")
        assert all(mount["Type"] == "tmpfs" and mount["Destination"] == "/tmp"
                   for mount in mounts), "No persistent input storage may be mounted"
        assert not info["NetworkSettings"]["Ports"], "Processor must not publish ports"
        proxy = json.loads(run("docker", "inspect", run(*compose, "ps", "--quiet", "browser")))[0]
        assert proxy["Config"]["User"] == "101:101" and proxy["HostConfig"]["ReadonlyRootfs"]
        assert proxy["HostConfig"]["CapDrop"] == ["ALL"]
        bindings = proxy["NetworkSettings"]["Ports"]["8080/tcp"]
        assert all(binding["HostIp"] == "127.0.0.1" for binding in bindings)
        networks = list(info["NetworkSettings"]["Networks"])
        assert len(networks) == 1
        assert json.loads(run("docker", "network", "inspect", networks[0]))[0]["Internal"]
        run("docker", "exec", container, "python", "-c",
            "import os,socket; assert os.getuid()==10001; "
            "s=socket.socket(); s.settimeout(1); assert s.connect_ex(('1.1.1.1',443))!=0; s.close()")
        base = "http://" + run(*compose, "port", "browser", "8080")

        def request(path, payload=None, authenticated=True):
            headers = {"Authorization": f"Bearer {key}"} if authenticated else {}
            data = None
            if payload is not None:
                data = json.dumps(payload).encode()
                headers["Content-Type"] = "application/json"
            try:
                response = urlopen(Request(base + path, data=data, headers=headers), timeout=15)
            except HTTPError as error:
                response = error
            with response:
                body = response.read().decode()
                return response.status, body, response.headers

        status, body, _ = request("/ready")
        assert status == 200 and json.loads(body)["engine"] == engine
        assert request("/workbench")[0] == 200
        assert request("/api/session", authenticated=False)[0] == 401
        assert request("/api/scan", {"text": "x" * 65_537})[0] == 413
        sentinel = "synthetic-error-sentinel"
        status, body, _ = request("/api/scan", {"text": {sentinel: sentinel}})
        assert status == 422 and sentinel not in body
        workflows = [
            ("support_ticket", {"text": 'Contact alice@example.com\nAuthorization: Bearer example header\n'
                '> password: |\n>   example first\n>   example second\n> Public context: investigate error 404.'}),
            ("ai_prompt", {"text": "Summarize alice@example.com; token=demo"}),
            ("email", {"sender": "alice@northwind.io", "recipients": "bob@example.com",
                       "subject": "Help for alice@example.com", "body": "password=demo"}),
        ]
        for use_case, fields in workflows:
            status, body, headers = request("/api/prepare", {"use_case": use_case, "fields": fields})
            assert status == 200 and headers["cache-control"] == "no-store"
            prepared = json.loads(body)
            assert prepared["candidate"]["engine"] == engine
            assert all(value not in body for value in ("alice@example.com", "=demo", "example header", "example first", "example second"))
            if use_case == "support_ticket":
                assert "Public context: investigate error 404." in prepared["candidate"]["fields"]["text"]
            payload = {"receipt": prepared["review"]["receipt"], "candidate": prepared["candidate"], "confirmed": True}
            status, body, _ = request("/api/review/export", payload)
            assert status == 200 and json.loads(body)["candidate"] == payload["candidate"]
            assert request("/api/review/export", payload)[0] == 410

        # Exercise bounded real HTTP load; the exact busy count is scheduling dependent.
        with ThreadPoolExecutor(max_workers=8) as pool:
            statuses = Counter(pool.map(lambda _: request("/api/scan", {
                "text": "Contact alice@example.com. " * (20 if args.opf else 80),
            })[0], range(32)))
        assert set(statuses) <= {200, 429, 503} and statuses[200] > 0
        assert request("/api/scan", {"text": "recovered"})[0] == 200
        _, body, _ = request("/api/prepare", {"use_case": "support_ticket", "fields": {"text": "alice@example.com"}})
        pending = json.loads(body)
        run(*compose, "restart", "sentinel")
        deadline = time.monotonic() + 180
        while True:
            try:
                if request("/ready")[0] == 200:
                    break
            except (URLError, ConnectionError):
                pass
            if time.monotonic() >= deadline:
                raise RuntimeError("Container did not become ready after restart")
            time.sleep(0.1)
        assert request("/api/review/export", {"receipt": pending["review"]["receipt"],
            "candidate": pending["candidate"], "confirmed": True})[0] == 410
        logs = run(*compose, "logs", "--no-color")
        assert all(value not in logs for value in (key, sentinel, "alice@example.com", "password=demo", "example first", "example header"))
        print(json.dumps({"status": "passed", "engine": engine, "review_workflows": 3,
                          "burst_statuses": statuses, "restart_receipt_rejected": True,
                          "non_root": True, "read_only": True, "external_connection_blocked": True}))
    finally:
        run(*compose, "down", "--remove-orphans")


if __name__ == "__main__":
    main()
