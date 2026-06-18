"""Serve the built Vite frontend from the FastAPI app (single-port deploy).

In the packaged desktop build there is no separate dev server: the static
assets in ``frontend/dist`` are served by FastAPI itself. The mount is added
LAST (after all API routes), and only if the build directory exists, so the
dev workflow (no build present) keeps working unchanged.
"""
from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles


def mount_frontend(app: FastAPI, dist_dir: Path) -> bool:
    """Mount the built frontend at ``/`` if ``dist_dir`` exists.

    Returns True if mounted, False if the directory is absent (dev mode).
    Must be called after all API routes are registered so they take
    precedence over the catch-all static mount.
    """
    if not dist_dir.is_dir():
        return False
    app.mount("/", StaticFiles(directory=str(dist_dir), html=True), name="frontend")
    return True
