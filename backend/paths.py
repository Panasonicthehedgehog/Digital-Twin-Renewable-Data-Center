"""Resolve data file paths consistently in dev and in a PyInstaller bundle.

When frozen by PyInstaller (onefile), bundled data lives under ``sys._MEIPASS``.
In development the same files live under the project root (the parent of the
``backend`` package). ``resource_path`` returns the correct absolute path in
both cases so the rest of the code can stay path-agnostic.
"""
from __future__ import annotations

import sys
from pathlib import Path


def project_root() -> Path:
    """Base directory for bundled resources.

    PyInstaller onefile: the temporary extraction dir (``sys._MEIPASS``).
    Dev: the repository root, i.e. the parent of the ``backend`` package.
    """
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        return Path(sys._MEIPASS)  # type: ignore[attr-defined]
    return Path(__file__).resolve().parent.parent


def resource_path(relative: str) -> Path:
    """Absolute path to a bundled resource given a project-root-relative path."""
    return project_root() / relative
