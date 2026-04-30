#!/usr/bin/env python3
"""
One-shot setup for the Renewable Data Center project.

Creates a Python virtual environment, installs backend dependencies,
and installs frontend npm packages. Works on macOS, Linux, and Windows.

Usage:
    python setup.py
"""
from __future__ import annotations

import platform
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
VENV_DIR = ROOT / ".venv"
FRONTEND_DIR = ROOT / "frontend"
REQUIREMENTS = ROOT / "requirements.txt"

IS_WINDOWS = platform.system() == "Windows"


def venv_python() -> Path:
    return VENV_DIR / ("Scripts" if IS_WINDOWS else "bin") / ("python.exe" if IS_WINDOWS else "python")


def run(cmd: list[str], cwd: Path | None = None) -> None:
    print(f"\n$ {' '.join(str(c) for c in cmd)}")
    subprocess.run(cmd, cwd=cwd, check=True)


def step(title: str) -> None:
    print(f"\n=== {title} ===")


def check_prerequisites() -> None:
    step("Checking prerequisites")
    if sys.version_info < (3, 10):
        sys.exit(f"Python 3.10+ required, found {sys.version.split()[0]}")
    print(f"Python {sys.version.split()[0]} OK")

    npm = shutil.which("npm")
    if not npm:
        sys.exit("npm not found. Please install Node.js 18+ from https://nodejs.org/")
    print(f"npm found at {npm}")


def create_venv() -> None:
    step("Creating virtual environment")
    if VENV_DIR.exists():
        print(f".venv already exists at {VENV_DIR} — skipping")
        return
    run([sys.executable, "-m", "venv", str(VENV_DIR)])


def install_backend() -> None:
    step("Installing backend dependencies")
    py = venv_python()
    run([str(py), "-m", "pip", "install", "--upgrade", "pip"])
    run([str(py), "-m", "pip", "install", "-r", str(REQUIREMENTS)])


def install_frontend() -> None:
    step("Installing frontend dependencies")
    npm = "npm.cmd" if IS_WINDOWS else "npm"
    run([npm, "install"], cwd=FRONTEND_DIR)


def main() -> int:
    try:
        check_prerequisites()
        create_venv()
        install_backend()
        install_frontend()
    except subprocess.CalledProcessError as e:
        print(f"\nSetup failed: command exited with status {e.returncode}", file=sys.stderr)
        return e.returncode

    print("\nSetup complete. Run the app with:  python start.py")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
