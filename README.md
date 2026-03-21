# Renewable Data Center: Location Intelligence ♻️

Research webapp to find optimal locations for hyperscaler AI data centers based on renewable energy availability.

**Motivation:** This is an Indo-German research project supporting UN SDGs 7, 9, 11, and 13 (sustainable energy and infrastructure).

### Goals

1. Enable permanently renewable data centers.
2. Identify regions where data centers could endanger the local renewable energy supply.
3. Assess regional energy impact for policymakers and energy suppliers.

## Getting Started

```bash
git clone https://github.com/YOUR_USERNAME/Digital-Twin-Renewable-Data-Center.git
cd Digital-Twin-Renewable-Data-Center
```

**Backend** (from project root):
```bash
.venv/bin/uvicorn backend.app:app --reload
```

**Frontend** (in a second terminal):
```bash
cd frontend
npm run dev
```

Open **http://localhost:5173** in your browser.
## Architecture 🏛️

### Frontend – Vite + Leaflet + Chart.js (vanilla JS)
- Interactive world map (CartoDB Positron basemap)
- Click any location to trigger a live renewable energy suitability analysis
- Sliding detail panel with score gauge, KPI chips, energy time series, and mix charts
- Location comparison view (up to 5 sites)
- Sidebar sliders for IT capacity (MW) and AI workload intensity

### Backend – FastAPI (Python)
- `POST /api/location/analyze` – fetches 7-day hourly weather from Open-Meteo, reverse-geocodes via Nominatim (OSM), and returns a multi-dimensional suitability score
- Digital twin simulation engine for step-by-step energy balance modelling (IT load → cooling → renewables → battery → hydrogen → grid)
- WebSocket `/ws/state` for real-time simulation state streaming

## Scoring Model

Each location is scored on four dimensions (0–100):

| Dimension | Weight | Basis |
|-----------|--------|-------|
| Solar     | 28 %   | Latitude band + 7-day avg. shortwave irradiance (Open-Meteo) |
| Wind      | 28 %   | 7-day avg. wind speed, cubic power law (optimal 7–12 m/s) |
| Climate   | 24 %   | Avg. temperature effect on PUE (optimal 8–14 °C) |
| Grid      | 20 %   | Country-level renewable grid reliability (ISO 3166-1 alpha-2 lookup) |

> Scores reflect the **current 7-day forecast**, not annual averages — seasonal variation is intentional.

## External APIs (no keys required)

- **[Open-Meteo](https://open-meteo.com/)** – free hourly weather forecast (7 days)
- **[Nominatim / OSM](https://nominatim.openstreetmap.org/)** – free reverse geocoding

## Data Sources

- Global power plant database: [WRI Global Power Plant Database](https://datasets.wri.org/datasets/global-power-plant-database)
