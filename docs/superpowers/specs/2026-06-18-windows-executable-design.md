# Design: Windows-`.exe` für Nicht-Techniker

**Datum:** 2026-06-18
**Status:** Approved (Design)
**Ziel:** Eine einfach startbare Windows-Version der App, die Nicht-Techniker per Doppelklick öffnen können — ausgeliefert als einzelne `.exe`.

## Problem

Die App besteht aktuell aus zwei Prozessen, die getrennt gestartet werden müssen:

- **Backend**: FastAPI/uvicorn auf `localhost:8000`
- **Frontend**: Vite-Dev-Server auf `localhost:5173`

Das erfordert installiertes Python **und** Node.js, zwei laufende Terminals und Verständnis für die Kommandozeile. Für Nicht-Techniker auf Windows ist das zu viel.

## Grundidee

Das Frontend wird **einmal statisch gebaut** (`npm run build` → `frontend/dist/`) und vom **FastAPI-Backend selbst mit ausgeliefert**. Damit bleibt nur **ein Prozess auf einem Port**. Dieser Prozess wird mit **PyInstaller** zu einer einzelnen `.exe` gebündelt. Beim Doppelklick startet der lokale Server und der Standardbrowser öffnet sich automatisch.

```
Doppelklick auf .exe
   └─ startet FastAPI (uvicorn) auf 127.0.0.1:<port>
   └─ FastAPI liefert: API-Routen + statisches Frontend (dist/)
   └─ öffnet Browser automatisch auf http://127.0.0.1:<port>
```

Node.js wird **nur zur Build-Zeit** (in GitHub Actions) benötigt, **nicht** zur Laufzeit beim Endnutzer. Die `.exe` enthält nur die gebündelte Python-Runtime + statisches Frontend.

## Entscheidungen

| Frage | Entscheidung |
|-------|--------------|
| Build-Umgebung | **GitHub Actions** (Windows-Runner) — kein eigenes Windows nötig, da Entwicklung auf macOS läuft und PyInstaller nicht cross-kompiliert. |
| Endprodukt | **Einzelne `.exe`** (`--onefile`). ZIP-Ordner (`--onedir`) als Fallback, falls SmartScreen/Antivirus stören. |
| Internet | Vorausgesetzt vorhanden (Open-Meteo, Nominatim, CARTO-Kartenkacheln). Keine Offline-Arbeit. |

## Komponenten

### 1. `frontend/src/main.js` — relative API-URL
- `const API_BASE = 'http://localhost:8000';` → `const API_BASE = '';`
- Das gebaute Frontend spricht das Backend dann über dieselbe Herkunft (same-origin, relativer Pfad) an. Einzige Frontend-Änderung.
- **Verifikation:** Im Dev-Modus muss die App weiterhin funktionieren. Da Dev-Frontend (5173) und Backend (8000) getrennt laufen, würde ein leerer `API_BASE` im Dev-Modus brechen. → Lösung: Vite-Dev-Proxy konfigurieren (`frontend/vite.config.js` neu), der `/api`, `/health`, `/ws` an `localhost:8000` weiterleitet. Damit funktioniert relativer Pfad in **beiden** Modi (Dev über Proxy, Bundle direkt).

### 2. `backend/app.py` — statisches Frontend ausliefern + Bundle-Pfade
- `resource_path(relative)`-Helfer: nutzt `sys._MEIPASS`, falls als PyInstaller-Bundle ausgeführt (`getattr(sys, 'frozen', False)`), sonst Projekt-Root. Damit werden `config/default_config.yaml` und `data/all_power_plants_clean.csv` sowohl im Dev-Modus als auch im Bundle gefunden.
- `CONFIG_PATH` über `resource_path()` auflösen statt fester relativer Pfad.
- `StaticFiles`-Mount von `frontend/dist` an `"/"` mit `html=True` — **nach** allen API-Routen registriert, damit `/api/*`, `/health`, `/ws/*` Vorrang haben. Mount nur, wenn `dist`-Verzeichnis existiert (im Dev-Modus ohne Build kein Fehler).

### 3. `backend/twin/location_scorer.py` — CSV-Pfad bundlefest
- Aktuell: `Path(__file__).parent.parent.parent / "data" / "all_power_plants_clean.csv"`.
- Im PyInstaller-Bundle zeigt `__file__` in `_MEIPASS`; die CSV wird passend nach `data/` gebündelt, sodass die Auflösung weiter stimmt. Alternativ den `resource_path()`-Helfer aus app.py verwenden (bevorzugt für Konsistenz).

### 4. `desktop.py` (neu) — Einstiegspunkt der `.exe`
- Freien lokalen Port wählen (Socket auf Port 0 binden, Nummer auslesen) — vermeidet Konflikt, falls 8000 belegt ist.
- uvicorn **programmatisch ohne `--reload`** starten (`uvicorn.run(app, host="127.0.0.1", port=port)`), Server in eigenem Thread; Hauptthread wartet per HTTP-Poll auf `/health`, öffnet dann `webbrowser.open(...)`.
- Freundliche Konsolenausgabe auf Deutsch: „Die App läuft. Browser öffnet sich… Dieses Fenster geöffnet lassen; zum Beenden einfach schließen."
- Sauberes Beenden beim Schließen des Fensters.

### 5. `datacenter-twin.spec` (neu) — PyInstaller-Konfiguration
- Modus `--onefile`, Entry = `desktop.py`.
- `datas`: `frontend/dist` → `frontend/dist`, `config` → `config`, `data` → `data`.
- `hiddenimports`: uvicorn-Worker/Loops nach Bedarf (`uvicorn.logging`, `uvicorn.loops.auto`, `uvicorn.protocols.*`), ggf. `backend.twin.location_scorer` (wird lazy importiert).
- Konsolenfenster sichtbar lassen (`console=True`) — dient als Status-/Stopp-Fenster für Nicht-Techniker.

### 6. `.github/workflows/build-windows.yml` (neu) — automatischer Build
- Trigger: manuell (`workflow_dispatch`) + auf Tags (`v*`).
- Steps auf `windows-latest`:
  1. Checkout
  2. `actions/setup-python` (3.11) + `actions/setup-node` (20)
  3. `cd frontend && npm ci && npm run build`
  4. `pip install -r requirements.txt pyinstaller`
  5. `pyinstaller datacenter-twin.spec`
  6. `actions/upload-artifact` mit `dist/*.exe`
  7. Bei Tag-Push optional: an GitHub Release anhängen.

### 7. `README.md` — Endnutzer-Abschnitt
- Kurzanleitung: `.exe` herunterladen → doppelklicken → bei SmartScreen-Warnung „Weitere Informationen → Trotzdem ausführen" → Browser öffnet sich → zum Beenden Fenster schließen.

## Bewusst NICHT enthalten (YAGNI)

- **Keine Offline-Fähigkeit** — Internet ist beim Zielnutzer gegeben.
- **Kein Code-Signing** — würde SmartScreen-Warnung beseitigen, kostet aber ein Zertifikat. Außer Scope.
- **Twin-Dashboard-Schreibpfad**: `PUT /api/config` schreibt `config`-Datei zurück; im Bundle liegt `config/` im schreibgeschützten `_MEIPASS`-Temp-Verzeichnis, daher gehen Änderungen beim Neustart verloren. Betrifft **nicht** die Karten-/Standortanalyse (die einzig genutzte Funktion). Wird als bekannte Einschränkung dokumentiert, nicht behoben.

## Bekannte Risiken / Hinweise

- **SmartScreen**: unsignierte `.exe` löst „Unbekannter Herausgeber"-Warnung aus. Einmalig per „Trotzdem ausführen" zu bestätigen. In README erklärt.
- **Antivirus-Fehlalarme**: `--onefile`-PyInstaller-Builds werden gelegentlich fälschlich erkannt. Fallback: `--onedir` (ZIP-Ordner).
- **Kaltstart**: `--onefile` entpackt sich bei jedem Start in ein Temp-Verzeichnis (~5–15 s). Akzeptiert; bei Bedarf `--onedir` als schnellere Alternative.

## Akzeptanzkriterien

1. Im Dev-Modus funktioniert die App weiter (Vite-Proxy leitet API-Calls ans Backend).
2. `npm run build` + lokaler Start von `desktop.py` (auf einem Testsystem) liefert die voll funktionsfähige Karten-App auf einem Port, Browser öffnet automatisch.
3. Der GitHub-Actions-Workflow erzeugt eine herunterladbare `.exe` als Artefakt.
4. Die `.exe` startet auf einem frischen Windows ohne installiertes Python/Node und zeigt die Standortanalyse korrekt an.
