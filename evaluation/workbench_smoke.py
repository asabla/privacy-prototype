"""Exercise the actual workbench DOM against a running, authenticated HTTP API."""

import os
import secrets
import socket
import subprocess
import threading
import time

import uvicorn

import backend.detector as detector
from backend.main import create_app
from backend.security import Settings


def main():
    key = secrets.token_urlsafe(32)
    detector._detector = detector.Detector("heuristic")
    app = create_app(Settings(api_key=key))
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        url = f"http://127.0.0.1:{sock.getsockname()[1]}"
        server = uvicorn.Server(uvicorn.Config(app, access_log=False, log_level="error"))
        thread = threading.Thread(target=server.run, kwargs={"sockets": [sock]}, daemon=True)
        thread.start()
        try:
            deadline = time.monotonic() + 10
            while not server.started:
                if not thread.is_alive() or time.monotonic() >= deadline:
                    raise RuntimeError("Workbench API did not start")
                time.sleep(0.01)
            env = {**os.environ, "SENTINEL_TEST_URL": url, "SENTINEL_TEST_KEY": key}
            subprocess.run(["node", "--test", "tests/workbench.integration.mjs"], env=env, check=True)
        finally:
            server.should_exit = True
            thread.join(timeout=10)
            if thread.is_alive():
                raise RuntimeError("Workbench API did not stop")


if __name__ == "__main__":
    main()
