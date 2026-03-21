# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

### Backend (FastAPI, Python)
```bash
# Start backend (from project root)
.venv/bin/uvicorn backend.app:app --reload
# or
python main.py

# Run tests
pytest tests/test_api.py

# Install Python deps
pip install -r requirements.txt
```

### Frontend (Vite, vanilla JS)
```bash
cd frontend
npm run dev      # dev server on http://localhost:5173
npm run build    # production build to frontend/dist/
npm run preview  # preview production build
```

## Architecture

Two independent processes communicate via HTTP (frontend → backend REST + WebSocket).

### Backend (`backend/`)
- **`app.py`** – FastAPI app. Hosts two systems: (1) `TwinRuntime` for digital twin simulation steps/scenarios/config, and (2) the `POST /api/location/analyze` endpoint that delegates to `location_scorer`.
- **`twin/location_scorer.py`** – The core location analysis engine. Fetches 7-day hourly forecasts from Open-Meteo, reverse-geocodes via Nominatim, computes four scores (solar, wind, climate, grid), and returns a composite score + 168-point time series. No API keys required.
- **`twin/core.py`** – `DigitalTwinEngine`: simulates energy balance across IT load → cooling → renewables → battery → hydrogen → grid, step by step. Scenarios (heatwave, dunkelflaute, grid_restriction, etc.) modify load/weather factors.
- **`twin/config.py`** – Pydantic models for twin configuration, loaded from `config/default_config.yaml`.

### Frontend (`frontend/src/`)
- **`main.js`** – All app logic. Manages `state` object (locations, markers, charts), drives Leaflet map clicks → API calls → UI updates. Vanilla JS only; no framework.
- **`index.html`** – 3-column layout: dark sidebar (config sliders + location list) | Leaflet map | sliding detail panel. Also contains a "Compare" view tab.

### Data Flow
1. User clicks map → `analyzeLocation(lat, lng, capacityMw, aiIntensity)` → `POST /api/location/analyze`
2. Backend calls Open-Meteo + Nominatim → scores → returns JSON with scores, time series, energy mix
3. Frontend renders: SVG gauge, score bars, KPI chips, renewable bar, two Chart.js charts

### Scoring Weights
Composite = 28% solar + 28% wind + 24% climate + 20% grid (all 0–100)

### WebSocket
`/ws/state` broadcasts simulation state every step; frontend does not currently consume this (it's wired for the twin dashboard use case, not the map view).

## Key Constraints
- Scores reflect the **current 7-day forecast**, not annual averages — seasonal variation is intentional and correct.
- Grid score is keyed on **ISO 3166-1 alpha-2 country code** (from Nominatim), not country name.
- Open-Meteo and Nominatim are free with no API keys, but rate-limited — avoid hammering them in tests.
- The `.venv/` is at the project root; no pyproject.toml, just `requirements.txt`.
