# Windows Executable Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Eine einzelne Windows-`.exe` erzeugen, die Nicht-Techniker per Doppelklick starten — der Server läuft lokal, das gebaute Frontend wird mit ausgeliefert, der Browser öffnet automatisch.

**Architecture:** Das Vite-Frontend wird statisch gebaut und vom FastAPI-Backend über `StaticFiles` mit ausgeliefert (ein Prozess, ein Port). Ein neuer Einstiegspunkt `desktop.py` startet uvicorn ohne Reload und öffnet den Browser. PyInstaller (`--onefile`) bündelt Python-Runtime, Frontend-Build, Config und CSV zu einer `.exe`. Ein GitHub-Actions-Workflow auf einem Windows-Runner erzeugt die `.exe` als Download-Artefakt.

**Tech Stack:** Python 3.11, FastAPI, uvicorn, PyInstaller, Vite, GitHub Actions (windows-latest).

**Spec:** `docs/superpowers/specs/2026-06-18-windows-executable-design.md`

---

## File Structure

| Datei | Verantwortung | Status |
|-------|---------------|--------|
| `backend/paths.py` | `resource_path()` — löst Datenpfade in Dev **und** im PyInstaller-Bundle auf | Neu |
| `backend/static_serving.py` | `mount_frontend()` — hängt das gebaute Frontend an die FastAPI-App | Neu |
| `backend/app.py` | Nutzt `resource_path` für `CONFIG_PATH`, ruft `mount_frontend` am Dateiende auf | Ändern |
| `backend/twin/location_scorer.py` | CSV-Pfad über `resource_path` statt `__file__`-Relativpfad | Ändern |
| `frontend/src/main.js` | `API_BASE` relativ (`''`) | Ändern |
| `frontend/vite.config.js` | Dev-Proxy für `/api`, `/health`, `/ws` → Backend | Neu |
| `desktop.py` | Einstiegspunkt der `.exe` (Server-Thread + Browser öffnen) | Neu |
| `datacenter-twin.spec` | PyInstaller-Build-Konfiguration | Neu |
| `.github/workflows/build-windows.yml` | Automatischer Windows-Build der `.exe` | Neu |
| `tests/test_paths.py` | Tests für `resource_path` | Neu |
| `tests/test_static_serving.py` | Tests für `mount_frontend` | Neu |
| `README.md` | Endnutzer-Abschnitt (Download, Doppelklick, SmartScreen) | Ändern |

---

## Task 1: Bundle-fester Pfad-Helfer (`backend/paths.py`)

**Files:**
- Create: `backend/paths.py`
- Test: `tests/test_paths.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_paths.py
import sys
from pathlib import Path

from backend.paths import resource_path, project_root


def test_resource_path_in_dev_resolves_under_project_root() -> None:
    # In dev mode (not frozen) paths resolve relative to the project root,
    # i.e. the parent of the backend/ package.
    p = resource_path("config/default_config.yaml")
    assert p == project_root() / "config" / "default_config.yaml"
    assert p.exists()  # the file really is there in the repo


def test_resource_path_uses_meipass_when_frozen(monkeypatch) -> None:
    # Simulate a PyInstaller onefile bundle.
    fake_meipass = Path("/tmp/_MEIfake")
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "_MEIPASS", str(fake_meipass), raising=False)
    p = resource_path("data/all_power_plants_clean.csv")
    assert p == fake_meipass / "data" / "all_power_plants_clean.csv"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/test_paths.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'backend.paths'`

- [ ] **Step 3: Write minimal implementation**

```python
# backend/paths.py
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/pytest tests/test_paths.py -v`
Expected: PASS (2 passed)

- [ ] **Step 5: Commit**

```bash
git add backend/paths.py tests/test_paths.py
git commit -m "feat: add bundle-aware resource_path helper"
```

---

## Task 2: Datenpfade über `resource_path` auflösen

**Files:**
- Modify: `backend/app.py:16` (CONFIG_PATH)
- Modify: `backend/twin/location_scorer.py:34` (csv_path)

- [ ] **Step 1: Update CONFIG_PATH in app.py**

In `backend/app.py`, nach den vorhandenen Imports den Helfer importieren und `CONFIG_PATH` ersetzen.

Add import (bei den `from backend.twin...`-Imports, Zeile ~13):

```python
from backend.paths import resource_path
```

Replace line 16:

```python
CONFIG_PATH = Path("config/default_config.yaml")
```

with:

```python
CONFIG_PATH = resource_path("config/default_config.yaml")
```

- [ ] **Step 2: Update csv_path in location_scorer.py**

In `backend/twin/location_scorer.py`, add import near the top (after `from pathlib import Path`, Zeile ~12):

```python
from backend.paths import resource_path
```

Replace line 34:

```python
    csv_path = Path(__file__).parent.parent.parent / "data" / "all_power_plants_clean.csv"
```

with:

```python
    csv_path = resource_path("data/all_power_plants_clean.csv")
```

- [ ] **Step 3: Run existing API tests to verify nothing broke**

Run: `.venv/bin/pytest tests/test_api.py -v`
Expected: PASS (3 passed) — the app still loads config and the CSV via the new paths.

- [ ] **Step 4: Commit**

```bash
git add backend/app.py backend/twin/location_scorer.py
git commit -m "refactor: resolve config and CSV paths via resource_path"
```

---

## Task 3: Frontend statisch ausliefern (`backend/static_serving.py`)

**Files:**
- Create: `backend/static_serving.py`
- Modify: `backend/app.py` (am Dateiende `mount_frontend` aufrufen)
- Test: `tests/test_static_serving.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_static_serving.py
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.static_serving import mount_frontend


def test_mount_returns_false_when_dist_missing(tmp_path: Path) -> None:
    app = FastAPI()
    mounted = mount_frontend(app, tmp_path / "does_not_exist")
    assert mounted is False


def test_mount_serves_index_html(tmp_path: Path) -> None:
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "index.html").write_text("<html>hello twin</html>", encoding="utf-8")

    app = FastAPI()

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    mounted = mount_frontend(app, dist)
    assert mounted is True

    client = TestClient(app)
    # API/route still takes precedence over the static mount
    assert client.get("/health").json() == {"status": "ok"}
    # Root serves the built index.html
    root = client.get("/")
    assert root.status_code == 200
    assert "hello twin" in root.text
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/test_static_serving.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'backend.static_serving'`

- [ ] **Step 3: Write minimal implementation**

```python
# backend/static_serving.py
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/pytest tests/test_static_serving.py -v`
Expected: PASS (2 passed)

- [ ] **Step 5: Wire mount into app.py (at the very end of the file)**

In `backend/app.py`, add the import near the other `from backend...` imports:

```python
from backend.static_serving import mount_frontend
```

Append at the **end** of `backend/app.py` (after the `ws_state` websocket handler, so the mount is registered last):

```python
# Serve the built frontend (single-port desktop build). No-op in dev when the
# build is absent; the Vite dev server serves the frontend there instead.
mount_frontend(app, resource_path("frontend/dist"))
```

- [ ] **Step 6: Run full backend test suite**

Run: `.venv/bin/pytest tests/ -v`
Expected: PASS (all tests). `test_api.py` still passes because no `frontend/dist` exists in the repo, so the mount is a no-op and `/api/*` routes are unaffected.

- [ ] **Step 7: Commit**

```bash
git add backend/static_serving.py tests/test_static_serving.py backend/app.py
git commit -m "feat: serve built frontend from FastAPI on a single port"
```

---

## Task 4: Frontend auf relative API-URL + Vite-Dev-Proxy

**Files:**
- Modify: `frontend/src/main.js:34`
- Create: `frontend/vite.config.js`

- [ ] **Step 1: Make API_BASE relative**

In `frontend/src/main.js`, replace line 34:

```javascript
const API_BASE = 'http://localhost:8000';
```

with:

```javascript
// Empty base = same origin. In the packaged build FastAPI serves both the
// frontend and the API on one port; in dev, vite.config.js proxies to :8000.
const API_BASE = '';
```

- [ ] **Step 2: Create the Vite dev proxy config**

Create `frontend/vite.config.js`:

```javascript
import { defineConfig } from 'vite';

// In dev the frontend runs on :5173 and the backend on :8000. With API_BASE=''
// the app calls same-origin paths like /api/... and /health; this proxy forwards
// those to the backend so the same code works in dev and in the packaged build.
export default defineConfig({
  server: {
    proxy: {
      '/api': { target: 'http://localhost:8000', changeOrigin: true },
      '/health': { target: 'http://localhost:8000', changeOrigin: true },
      '/ws': { target: 'http://localhost:8000', ws: true, changeOrigin: true },
    },
  },
});
```

- [ ] **Step 3: Verify the production build succeeds**

Run: `cd frontend && npm install && npm run build`
Expected: build completes, `frontend/dist/index.html` and `frontend/dist/assets/` are created. (No errors about vite.config.js.)

- [ ] **Step 4: Verify dev mode still works (manual smoke test)**

Run backend: `.venv/bin/uvicorn backend.app:app --reload`
Run frontend (second terminal): `cd frontend && npm run dev`
Open http://localhost:5173, click a location on the map.
Expected: analysis loads (network calls to `/api/location/analyze` succeed via the proxy). Press Ctrl+C in both terminals to stop.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/main.js frontend/vite.config.js
git commit -m "feat: use same-origin API base with vite dev proxy"
```

---

## Task 5: Desktop-Einstiegspunkt (`desktop.py`)

**Files:**
- Create: `desktop.py`

- [ ] **Step 1: Write desktop.py**

Create `desktop.py` in the project root:

```python
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
    print("  Renewable Data Center – Standortanalyse")
    print("=" * 60)
    print("  Die App startet... bitte einen Moment Geduld.")

    if wait_until_ready(url):
        print(f"  Geöffnet im Browser: {url}")
        print("  Dieses Fenster bitte GEÖFFNET lassen.")
        print("  Zum Beenden einfach dieses Fenster schließen.")
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
```

- [ ] **Step 2: Verify it runs in dev (manual smoke test)**

First ensure a frontend build exists so the single-port mode is exercised:
Run: `cd frontend && npm run build && cd ..`
Run: `.venv/bin/python desktop.py`
Expected: console prints the banner, browser opens at `http://127.0.0.1:<port>`, the full map app loads and a location click returns an analysis — all on the **one** port. Close the window / Ctrl+C to stop.

- [ ] **Step 3: Commit**

```bash
git add desktop.py
git commit -m "feat: add desktop entry point that serves app and opens browser"
```

---

## Task 6: PyInstaller-Spec (`datacenter-twin.spec`)

**Files:**
- Create: `datacenter-twin.spec`

- [ ] **Step 1: Write the spec file**

Create `datacenter-twin.spec` in the project root:

```python
# -*- mode: python ; coding: utf-8 -*-
# PyInstaller spec for the single-file Windows build.
# Build (on Windows, after `npm run build` in frontend/):
#   pip install -r requirements.txt pyinstaller
#   pyinstaller datacenter-twin.spec
# Output: dist/RenewableDataCenter.exe

block_cipher = None

datas = [
    ("frontend/dist", "frontend/dist"),
    ("config", "config"),
    ("data", "data"),
]

hiddenimports = [
    "uvicorn.logging",
    "uvicorn.loops",
    "uvicorn.loops.auto",
    "uvicorn.protocols",
    "uvicorn.protocols.http",
    "uvicorn.protocols.http.auto",
    "uvicorn.protocols.websockets",
    "uvicorn.protocols.websockets.auto",
    "uvicorn.lifespan",
    "uvicorn.lifespan.on",
    "backend.twin.location_scorer",
]

a = Analysis(
    ["desktop.py"],
    pathex=[],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name="RenewableDataCenter",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,   # console doubles as the status/stop window
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
```

- [ ] **Step 2: Note — cannot build locally (macOS)**

This spec is verified by the GitHub Actions workflow (Task 7) on a Windows runner. PyInstaller does not cross-compile, so there is no local build/run step here. Spec correctness is confirmed by a green workflow run producing `dist/RenewableDataCenter.exe`.

- [ ] **Step 3: Commit**

```bash
git add datacenter-twin.spec
git commit -m "build: add PyInstaller onefile spec for Windows exe"
```

---

## Task 7: GitHub-Actions-Workflow (`.github/workflows/build-windows.yml`)

**Files:**
- Create: `.github/workflows/build-windows.yml`

- [ ] **Step 1: Write the workflow**

Create `.github/workflows/build-windows.yml`:

```yaml
name: Build Windows Executable

on:
  workflow_dispatch:        # manuell startbar im GitHub-UI
  push:
    tags:
      - "v*"                # baut automatisch bei Versions-Tags

jobs:
  build:
    runs-on: windows-latest
    steps:
      - name: Checkout
        uses: actions/checkout@v4

      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: "3.11"

      - name: Set up Node
        uses: actions/setup-node@v4
        with:
          node-version: "20"

      - name: Build frontend
        working-directory: frontend
        run: |
          npm ci
          npm run build

      - name: Install Python dependencies
        run: |
          python -m pip install --upgrade pip
          pip install -r requirements.txt pyinstaller

      - name: Build executable
        run: pyinstaller datacenter-twin.spec

      - name: Upload executable artifact
        uses: actions/upload-artifact@v4
        with:
          name: RenewableDataCenter-windows
          path: dist/RenewableDataCenter.exe

      - name: Attach to release
        if: startsWith(github.ref, 'refs/tags/')
        uses: softprops/action-gh-release@v2
        with:
          files: dist/RenewableDataCenter.exe
```

- [ ] **Step 2: Commit and push**

```bash
git add .github/workflows/build-windows.yml
git commit -m "ci: add Windows .exe build workflow"
git push
```

- [ ] **Step 3: Trigger and verify the build**

In GitHub → Actions → "Build Windows Executable" → "Run workflow".
Expected: the job succeeds; the run page shows a downloadable artifact `RenewableDataCenter-windows` containing `RenewableDataCenter.exe`.
(Note: `npm ci` requires a committed `frontend/package-lock.json`. If the run fails at `npm ci` because the lockfile is missing, generate it locally with `cd frontend && npm install`, commit `frontend/package-lock.json`, and re-run.)

---

## Task 8: Endnutzer-Dokumentation (README)

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Add an end-user section to README.md**

Insert the following section in `README.md` directly under the `## Getting Started` heading (before "### Prerequisites"), so non-technical users see it first:

```markdown
### Für Endnutzer: fertige Windows-App (kein Setup nötig)

Wenn du die App nur **benutzen** willst (kein Python/Node nötig):

1. Lade die Datei **`RenewableDataCenter.exe`** herunter
   (GitHub → Actions → letzter „Build Windows Executable"-Lauf → Artefakt
   `RenewableDataCenter-windows`, oder vom Release).
2. **Doppelklick** auf die `.exe`.
3. Beim ersten Start warnt Windows evtl. mit „Der Computer wurde durch
   Windows geschützt" (unbekannter Herausgeber). Klicke auf
   **„Weitere Informationen" → „Trotzdem ausführen"**.
4. Es öffnet sich ein kleines schwarzes Fenster und nach einigen Sekunden
   automatisch der Browser mit der App.
5. **Wichtig:** Das schwarze Fenster geöffnet lassen, solange du die App
   nutzt. Zum Beenden einfach das Fenster schließen.

> Eine Internetverbindung ist erforderlich (Wetter- und Kartendaten).
> Der erste Start dauert etwas länger, da sich die App intern entpackt.
```

- [ ] **Step 2: Verify the README renders (visual check)**

Run: `git diff README.md`
Expected: the new section appears under `## Getting Started`, Markdown is well-formed (headings, numbered list, blockquote).

- [ ] **Step 3: Commit**

```bash
git add README.md
git commit -m "docs: add end-user instructions for the Windows exe"
```

---

## Self-Review Notes

- **Spec coverage:** API_BASE relativ (Task 4) ✓; statisches Ausliefern + resource_path (Tasks 1–3) ✓; CSV-Pfad bundlefest (Task 2) ✓; desktop.py Einstiegspunkt (Task 5) ✓; PyInstaller-Spec onefile (Task 6) ✓; GitHub-Actions-Workflow (Task 7) ✓; README-Endnutzerteil (Task 8) ✓. Vite-Dev-Proxy (im Spec als Verifikationsbedingung genannt) → Task 4 ✓.
- **Known limitation aus Spec** (`PUT /api/config` schreibt in schreibgeschütztes `_MEIPASS`): bewusst nicht behoben, betrifft nicht die Karten-/Standortanalyse. Kein Task nötig.
- **Type/Name-Konsistenz:** `resource_path` / `project_root` (Task 1) werden in Tasks 2 & 3 mit identischer Signatur genutzt; `mount_frontend(app, dist_dir)` (Task 3) konsistent verwendet.
- **Build-Reihenfolge im Workflow:** Frontend-Build **vor** PyInstaller, damit `frontend/dist` für das Bundling existiert ✓.
