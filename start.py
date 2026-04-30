#!/usr/bin/env python3
"""
Start backend (FastAPI/uvicorn) and frontend (Vite) in parallel.

Press Ctrl+C once to stop both processes cleanly.
Works on macOS, Linux, and Windows. Run after `python setup.py`.

Usage:
    python start.py
"""
from __future__ import annotations

import os
import platform
import signal
import subprocess
import sys
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parent
VENV_DIR = ROOT / ".venv"
FRONTEND_DIR = ROOT / "frontend"

IS_WINDOWS = platform.system() == "Windows"


def venv_python() -> Path:
    return VENV_DIR / ("Scripts" if IS_WINDOWS else "bin") / ("python.exe" if IS_WINDOWS else "python")


def ensure_setup() -> None:
    if not venv_python().exists():
        sys.exit("Virtual environment not found. Run `python setup.py` first.")
    if not (FRONTEND_DIR / "node_modules").exists():
        sys.exit("Frontend dependencies missing. Run `python setup.py` first.")


def popen_kwargs() -> dict:
    """Spawn each child in its own process group so we can signal the whole tree."""
    if IS_WINDOWS:
        return {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP}
    return {"start_new_session": True}


def start_backend() -> subprocess.Popen:
    py = str(venv_python())
    cmd = [py, "-m", "uvicorn", "backend.app:app", "--reload", "--host", "0.0.0.0", "--port", "8000"]
    print(f"Starting backend:  {' '.join(cmd)}")
    return subprocess.Popen(cmd, cwd=ROOT, **popen_kwargs())


def start_frontend() -> subprocess.Popen:
    npm = "npm.cmd" if IS_WINDOWS else "npm"
    cmd = [npm, "run", "dev"]
    print(f"Starting frontend: {' '.join(cmd)} (in {FRONTEND_DIR})")
    return subprocess.Popen(cmd, cwd=FRONTEND_DIR, **popen_kwargs())


def stop(proc: subprocess.Popen, name: str) -> None:
    if proc.poll() is not None:
        return
    print(f"Stopping {name}...")
    try:
        if IS_WINDOWS:
            proc.send_signal(signal.CTRL_BREAK_EVENT)
        else:
            os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
        proc.wait(timeout=5)
    except (subprocess.TimeoutExpired, ProcessLookupError, OSError):
        try:
            if not IS_WINDOWS:
                os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
            else:
                proc.kill()
        except (ProcessLookupError, OSError):
            pass


def main() -> int:
    ensure_setup()

    backend = start_backend()
    frontend = start_frontend()

    print("\nBackend:  http://localhost:8000")
    print("Frontend: http://localhost:5173")
    print("Press Ctrl+C to stop.\n")

    shutdown = threading.Event()

    def request_shutdown(signum, _frame):
        print(f"\nReceived signal {signum}, shutting down...")
        shutdown.set()

    signal.signal(signal.SIGINT, request_shutdown)
    if not IS_WINDOWS:
        signal.signal(signal.SIGTERM, request_shutdown)

    try:
        while not shutdown.is_set():
            if backend.poll() is not None:
                print("Backend exited unexpectedly.")
                break
            if frontend.poll() is not None:
                print("Frontend exited unexpectedly.")
                break
            shutdown.wait(0.5)
    finally:
        stop(frontend, "frontend")
        stop(backend, "backend")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
