# Renewable Data Center: Location Intelligence ♻️

Research webapp to find optimal locations for hyperscaler AI data centers based on renewable energy availability.

**Motivation:** This is an Indo-German research project supporting UN SDGs 7, 9, 11, and 13 (sustainable energy and infrastructure).

### Goals

1. Enable permanently renewable data centers.
2. Identify regions where data centers could endanger the local renewable energy supply.
3. Assess regional energy impact for policymakers and energy suppliers.

## Getting Started

### Prerequisites

- **Python** 3.10 or newer — [python.org](https://www.python.org/downloads/)
- **Node.js** 18 or newer (includes npm) — [nodejs.org](https://nodejs.org/)
- **Git**

Verify your installation:
```bash
python --version    # or python3 --version
node --version
npm --version
```

### Quick Start (recommended)

Two cross-platform helper scripts handle the full setup. They work on **macOS, Linux, and Windows**.

```bash
git clone https://github.com/YOUR_USERNAME/Digital-Twin-Renewable-Data-Center.git
cd Digital-Twin-Renewable-Data-Center

python setup.py    # one-time: creates .venv, installs all dependencies
python start.py    # starts backend + frontend in parallel
```

> On some systems the Python launcher is called `python3` instead of `python`. Use whichever resolves to Python 3.10+.

Open **http://localhost:5173** in your browser. Press **Ctrl+C** in the terminal to stop both servers.

### Manual Setup (alternative)

If you prefer to run the steps yourself:

**1. Create and activate a virtual environment**

macOS / Linux:
```bash
python3 -m venv .venv
source .venv/bin/activate
```

Windows (PowerShell):
```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
```

Windows (cmd):
```cmd
python -m venv .venv
.venv\Scripts\activate.bat
```

**2. Install backend dependencies**
```bash
pip install -r requirements.txt
```

**3. Install frontend dependencies**
```bash
cd frontend
npm install
cd ..
```

**4. Run the app — two terminals**

Terminal 1 (backend):
```bash
# macOS / Linux
.venv/bin/uvicorn backend.app:app --reload
# Windows
.venv\Scripts\uvicorn backend.app:app --reload
```

Terminal 2 (frontend):
```bash
cd frontend
npm run dev
```

Open **http://localhost:5173** in your browser.

### Troubleshooting

| Problem | Solution |
|---------|----------|
| `python: command not found` | Try `python3` instead, or install Python from [python.org](https://www.python.org/downloads/). |
| `npm: command not found` | Install Node.js from [nodejs.org](https://nodejs.org/). |
| Windows: "running scripts is disabled" when activating venv | Run PowerShell as admin and execute `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned`. |
| Port 8000 or 5173 already in use | Stop the other process, or change the port (`--port 8001` for uvicorn; edit `vite.config.js` for Vite). |
| Frontend cannot reach backend | Make sure the backend is running on `localhost:8000` and CORS is allowed (default in `backend/app.py`). |
| `pip install` fails on a corporate network | Configure your proxy: `pip install --proxy http://user:pass@proxy:port -r requirements.txt`. |
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
