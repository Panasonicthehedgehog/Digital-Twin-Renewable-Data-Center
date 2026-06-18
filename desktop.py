#!/usr/bin/env python3
"""Desktop entry point for the packaged Windows app.

Starts the FastAPI server (no reload) on a free local port in a background
thread, waits until it answers /health, then opens the default browser.
Closing the console window stops the server.

Run in dev:  python desktop.py
Packaged:    double-click the .exe produced by datacenter-twin.spec
"""
from __future__ import annotations

import socket
import threading
import time
import urllib.request
import webbrowser

import uvicorn

from backend.app import app

HOST = "127.0.0.1"


def find_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind((HOST, 0))
        return s.getsockname()[1]


def wait_until_ready(url: str, timeout_s: float = 30.0) -> bool:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(f"{url}/health", timeout=1):
                return True
        except Exception:
            time.sleep(0.4)
    return False


def main() -> int:
    port = find_free_port()
    url = f"http://{HOST}:{port}"

    config = uvicorn.Config(app, host=HOST, port=port, log_level="warning")
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()

    print("=" * 60)
    print("  Renewable Data Center - Standortanalyse")
    print("=" * 60)
    print("  Die App startet... bitte einen Moment Geduld.")

    if wait_until_ready(url):
        print(f"  Geoeffnet im Browser: {url}")
        print("  Dieses Fenster bitte GEOEFFNET lassen.")
        print("  Zum Beenden einfach dieses Fenster schliessen.")
        webbrowser.open(url)
    else:
        print("  FEHLER: Server konnte nicht gestartet werden.")
        return 1
    print("=" * 60)

    try:
        while thread.is_alive():
            thread.join(0.5)
    except KeyboardInterrupt:
        server.should_exit = True
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
