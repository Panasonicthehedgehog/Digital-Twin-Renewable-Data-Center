# Hyperscale AI Data Center Digital Twin

Research-oriented, out-of-the-box digital twin for hyperscaler AI data centers.

## What this system models

- Hierarchical infrastructure: **Server → Rack → Hall → Block → Data Center**
- Dynamic AI IT load and cooling/infrastructure overhead
- Energy portfolio: grid, PV, wind, battery, hydrogen bridge
- Configurable weather and stress scenarios (heatwave, dunkelflaute, grid restriction, load spikes)
- Explicit operational limits with failure detection and hydrogen resilience visibility

## Repository layout

```text
backend/
  app.py                 # FastAPI app (REST + WebSocket)
  twin/
    config.py            # Pydantic config schema + YAML IO
    core.py              # Simulation engine, hierarchy aggregation, energy balance
config/
  default_config.yaml    # Runtime-editable deployment config
frontend/
  index.html
  package.json
  src/main.js            # Browser dashboard + controls + websocket client
  src/styles.css
main.py                  # One-command backend launcher (python main.py)
tests/test_api.py
```

## Architecture

### 1) Twin Core (Python)
- Deterministic step simulation (`timestep_minutes`)
- Explainable calculations for:
  - IT load (server count × utilization)
  - Cooling load (COP + ambient temperature impact)
  - Infrastructure overhead
  - Renewable generation (solar + wind weather-dependent)
  - Dispatch order: renewables → battery → hydrogen bridge → grid → unmet load
- Scenario engine with reproducible stress events
- Hierarchical aggregation for visualization heatmaps

### 2) API Layer
- REST endpoints:
  - `GET /api/state`
  - `GET /api/scenarios`
  - `POST /api/scenario`
  - `POST /api/simulate`
  - `GET /api/config`
  - `PUT /api/config`
- WebSocket stream:
  - `ws://localhost:8000/ws/state`

### 3) Frontend
- Browser app (Vite, no Electron)
- Live stress KPIs and pseudo-3D rack heatmap
- Weather overlay, energy flow panel, failure status
- Control panel for scenario selection and runtime config updates

## Run locally

### Backend
```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python main.py
```

### Frontend
```bash
cd frontend
npm install
npm run dev
```

Open `http://localhost:5173`.

## Configuration

Primary configuration file: `config/default_config.yaml`.

All core parameters are editable at runtime through:
1. **YAML config** (`/api/config` load/save path)
2. **Frontend control panel** (AI intensity, grid capacity, hydrogen size; extensible)

No simulation constants are hardcoded outside the config schema defaults.

## Scientific assumptions & limitations

Assumptions and simplifications are documented in `backend/twin/core.py` docstring/comments.

- Designed for design-science experimentation and scenario comparison
- Deterministic mode enabled by default for reproducibility
- Not a power-flow solver; use as an explainable decision-support artifact

## Testing

```bash
pytest -q
```
