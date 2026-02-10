# Digital-Twin-Renewable-Data-Center ♻️

Dieses Repository enthält nun einen lauffähigen, detaillierten **Digital Twin eines Hyperscaler Data Centers** mit:

- **Twin.js Modellschicht** (Halls, Racks, Renewables, Batteries, Weather, Grid)
- **Python Data Pipeline API** (FastAPI) zum Laden von Telemetrie
- **Web-Dashboard** zur Visualisierung des Live-Zustands
- **iTwin.js-basierte Topology-View** (über `@itwin/core-geometry`) für eine 3D-ähnliche Hall-Darstellung

## Architektur

- `app/static/twin.js`  
  Modelllogik des Twins (Objekte + Aggregationen wie IT-Load, Facility-Load, Renewable-Coverage)
- `app/main.py`  
  FastAPI-Endpunkte + In-Memory Twin-State-Store
- `app/static/index.html`, `app/static/app.js`, `app/static/styles.css`, `app/static/itwin-topology.js`  
  UI für Betriebsstatus, Hall/Rack-Details, Energieabdeckung und iTwin.js-Topology-Visualisierung
- `scripts/load_pipeline_data.py`  
  Python-Loader für JSON, JSONL/NDJSON und CSV

## Schnellstart

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload
```

Dann im Browser öffnen:

- `http://localhost:8000` (Dashboard)
- `http://localhost:8000/api/v1/state` (aktueller Twin-State)

## Data Pipeline Zugänge

### 1) Einzel-Event senden

```bash
curl -X POST http://localhost:8000/api/v1/telemetry \
  -H "Content-Type: application/json" \
  -d '{
    "weather": {"ambientTempC": 31.5, "ghiWm2": 950},
    "halls": [{"id": "hall-a", "racks": [{"id": "a-r1", "cpuUtilization": 0.89}]}]
  }'
```

### 2) Bulk-Ingestion senden

```bash
curl -X POST http://localhost:8000/api/v1/telemetry/bulk \
  -H "Content-Type: application/json" \
  -d '[
    {"grid": {"priceEurPerMwh": 185}},
    {"renewables": [{"id": "solar-west", "outputKw": 17250}]}
  ]'
```

### 3) Python Loader verwenden

Mit Beispiel-Datei:

```bash
python scripts/load_pipeline_data.py data/sample_telemetry.jsonl --api-url http://localhost:8000/api/v1/telemetry
```

Bulk-Modus:

```bash
python scripts/load_pipeline_data.py data/sample_telemetry.jsonl --api-url http://localhost:8000/api/v1/telemetry --bulk
```

## Tests

```bash
pytest -q
```
