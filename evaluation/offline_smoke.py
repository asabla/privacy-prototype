"""Real OPF preload and workflow check with network sockets denied in-process."""

import os
import socket
from unittest.mock import patch


def main():
    os.environ.update(SENTINEL_ENGINE="opf", SENTINEL_PRELOAD="1",
                      HF_HUB_OFFLINE="1", HF_HUB_DISABLE_TELEMETRY="1",
                      HF_HUB_DISABLE_IMPLICIT_TOKEN="1")

    def deny_network(*args, **kwargs):
        raise RuntimeError("Offline check attempted an outbound network connection")

    # TCP/UDP and DNS are forbidden; Unix socketpairs used by asyncio are local.
    original_connect = socket.socket.connect
    def local_connect(sock, address):
        if sock.family in (socket.AF_INET, socket.AF_INET6):
            deny_network()
        return original_connect(sock, address)

    with patch.object(socket.socket, "connect", local_connect), \
            patch.object(socket.socket, "connect_ex", deny_network), \
            patch.object(socket.socket, "sendto", deny_network), \
            patch.object(socket, "getaddrinfo", deny_network):
        from evaluation.smoke import main as smoke
        smoke(preload=True)


if __name__ == "__main__":
    main()
