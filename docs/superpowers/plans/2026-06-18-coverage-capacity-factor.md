# Capacity-Factor-Weighted Load Coverage Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the load-coverage metric compare regional renewable *expected generation* (nameplate × capacity factor) against datacenter demand, instead of raw nameplate capacity.

**Architecture:** A new pure function `expected_generation_mw` weights each renewable fuel's nameplate MW by a capacity factor — Solar/Wind weather-derived from the already-fetched forecast, other fuels static — and `analyze_location` feeds this into the existing `score_load_coverage`. The CF-weighted figure is computed once in the backend (slider-independent) and stored in `regional_grid`; the frontend uses it as the coverage numerator and displays it alongside nameplate.

**Tech Stack:** Python 3.13 / FastAPI / pytest (backend), vanilla JS / Vite (frontend).

## Global Constraints

- CF correction affects ONLY load-coverage (`coverage_ratio_pct`, `coverage_possible`, `s_load_coverage`). Grid score (`score_grid_regional`) and the fuel-mix chart stay on nameplate.
- Solar CF = `min(0.40, avg_irr/1000 * 0.80)`. Wind CF: shear `v_hub = avg_wind * 1.4`, then piecewise curve (≤3 → 0; 3–12 → `(v_hub-3)/9*0.55`; 12–25 → 0.55; >25 → 0). Static CFs: Hydro 0.40, Biomass 0.60, Geothermal 0.80, Wave and Tidal 0.30; other renewables default 0.40; non-renewables ignored.
- `effective_renewable_mw` exposed in `regional_grid`; `renewable_mw` (nameplate) stays unchanged.
- Frontend coverage numerator = `regional_grid.effective_renewable_mw` (slider-independent, constant per location).
- Tests: `.venv/bin/python -m pytest -q` from project root, no live network (monkeypatch `get_location_info`, `fetch_weather_forecast`, `get_regional_plant_stats`). Use `pytest.approx` for float comparisons.
- Known quirk: a non-isolated config test may dirty `config/default_config.yaml`. If modified after the full suite, revert with `git checkout -- config/default_config.yaml` — never stage it.
- Commit messages must NOT contain a Co-Authored-By trailer.

---

### Task 1: Capacity-factor functions + `expected_generation_mw`

**Files:**
- Modify: `backend/twin/location_scorer.py` (add module constants + 3 pure functions after `score_load_coverage`, around line 140)
- Test: `tests/test_capacity_factor.py` (create)

**Interfaces:**
- Produces: `solar_capacity_factor(avg_irr_wm2: float) -> float`
- Produces: `wind_capacity_factor(avg_wind_ms: float) -> float`
- Produces: `expected_generation_mw(fuel_mw: dict[str, float], avg_irr_wm2: float, avg_wind_ms: float) -> float` (rounded 1 dp)

- [ ] **Step 1: Write the failing tests**

Create `tests/test_capacity_factor.py`:

```python
import pytest

from backend.twin import location_scorer as ls


def test_solar_capacity_factor():
    assert ls.solar_capacity_factor(0.0) == 0.0
    assert ls.solar_capacity_factor(250.0) == pytest.approx(0.20)   # 250/1000*0.80
    assert ls.solar_capacity_factor(1000.0) == 0.40                 # 0.80 capped to 0.40


def test_wind_capacity_factor():
    assert ls.wind_capacity_factor(0.0) == 0.0
    assert ls.wind_capacity_factor(2.0) == 0.0                      # v_hub=2.8 <= 3 -> 0
    assert ls.wind_capacity_factor(7.0) == pytest.approx((7.0 * 1.4 - 3.0) / 9.0 * 0.55)
    assert ls.wind_capacity_factor(10.0) == 0.55                    # v_hub=14 -> rated
    assert ls.wind_capacity_factor(20.0) == 0.0                     # v_hub=28 > 25 -> cut-out


def test_expected_generation_mw_weights_each_fuel():
    fuel = {"Solar": 1000.0, "Wind": 1000.0, "Hydro": 100.0, "Coal": 5000.0}
    result = ls.expected_generation_mw(fuel, avg_irr_wm2=250.0, avg_wind_ms=10.0)
    # Solar 1000*0.20 + Wind 1000*0.55 + Hydro 100*0.40 ; Coal ignored
    assert result == pytest.approx(1000 * 0.20 + 1000 * 0.55 + 100 * 0.40, abs=0.05)


def test_expected_generation_mw_never_exceeds_nameplate():
    fuel = {"Solar": 500.0, "Wind": 500.0, "Geothermal": 200.0}
    result = ls.expected_generation_mw(fuel, avg_irr_wm2=300.0, avg_wind_ms=8.0)
    assert 0.0 < result <= sum(fuel.values())


def test_expected_generation_mw_empty():
    assert ls.expected_generation_mw({}, 200.0, 8.0) == 0.0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_capacity_factor.py -q`
Expected: FAIL (`AttributeError: module ... has no attribute 'solar_capacity_factor'`).

- [ ] **Step 3: Implement the functions**

In `backend/twin/location_scorer.py`, immediately after `score_load_coverage` (around line 140), add:

```python
# Static capacity factors for dispatchable / non-weather renewable fuels.
_STATIC_CAPACITY_FACTORS: dict[str, float] = {
    "Hydro": 0.40,
    "Biomass": 0.60,
    "Geothermal": 0.80,
    "Wave and Tidal": 0.30,
}
_DEFAULT_RENEWABLE_CF = 0.40


def solar_capacity_factor(avg_irr_wm2: float) -> float:
    """Solar CF from mean irradiance (W/m²): normalised against STC (1000 W/m²)
    with a 0.80 performance ratio (system/inverter losses); capped at 0.40."""
    return min(0.40, max(0.0, avg_irr_wm2) / 1000.0 * 0.80)


def wind_capacity_factor(avg_wind_ms: float) -> float:
    """Wind CF from 10 m mean wind speed via a simplified power curve.

    Applies a 1.4× shear correction to ~100 m hub height (power-law α≈0.14),
    then a piecewise curve: cut-in 3 m/s, rated 12 m/s (CF 0.55), cut-out 25 m/s.
    This is a simplified mean-wind proxy, not a time-series integration.
    """
    v_hub = max(0.0, avg_wind_ms) * 1.4
    if v_hub <= 3.0 or v_hub > 25.0:
        return 0.0
    if v_hub < 12.0:
        return (v_hub - 3.0) / 9.0 * 0.55
    return 0.55


def expected_generation_mw(
    fuel_mw: dict[str, float], avg_irr_wm2: float, avg_wind_ms: float
) -> float:
    """Expected mean renewable generation (MW): per-fuel nameplate capacity
    weighted by its capacity factor. Solar/Wind CFs are weather-derived; other
    renewable fuels use static literature CFs. Non-renewable fuels are ignored.
    """
    solar_cf = solar_capacity_factor(avg_irr_wm2)
    wind_cf = wind_capacity_factor(avg_wind_ms)
    total = 0.0
    for fuel, mw in fuel_mw.items():
        if fuel == "Solar":
            total += mw * solar_cf
        elif fuel == "Wind":
            total += mw * wind_cf
        elif fuel in _STATIC_CAPACITY_FACTORS:
            total += mw * _STATIC_CAPACITY_FACTORS[fuel]
        elif fuel in _RENEWABLE_FUELS:
            total += mw * _DEFAULT_RENEWABLE_CF
        # non-renewable fuels are ignored
    return round(total, 1)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_capacity_factor.py -q`
Expected: PASS (5 tests).

- [ ] **Step 5: Commit**

```bash
git add backend/twin/location_scorer.py tests/test_capacity_factor.py
git commit -m "feat: add capacity-factor functions for expected renewable generation (#3)"
```

---

### Task 2: Use expected generation in `analyze_location`

**Files:**
- Modify: `backend/twin/location_scorer.py` (`analyze_location`, steps 6 + regional_grid dict, around lines 409–455)
- Test: `tests/test_location_scorer.py` (add one test to the existing file)

**Interfaces:**
- Consumes: `expected_generation_mw` (Task 1), `score_load_coverage` (existing).
- Produces: `analyze_location(...)["regional_grid"]["effective_renewable_mw"]`; `scores.load_coverage` now derived from expected generation.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_location_scorer.py` (it already defines `_fake_weather`):

```python
def test_analyze_location_coverage_uses_expected_generation(monkeypatch):
    monkeypatch.setattr(ls, "get_location_info",
                        lambda lat, lng: {"city": "X", "country": "Y",
                                          "country_code": "DE", "display": "X, Y"})
    monkeypatch.setattr(ls, "fetch_weather_forecast", _fake_weather)
    monkeypatch.setattr(ls, "get_regional_plant_stats",
                        lambda lat, lng: {"fuel_mw": {"Solar": 500.0, "Wind": 300.0},
                                          "total_mw": 1000.0, "renewable_mw": 800.0,
                                          "plant_count": 5, "top_plants": []})
    result = ls.analyze_location(0.0, 0.0, servers=1000, ai_intensity=0.5)

    rg = result["regional_grid"]
    assert "effective_renewable_mw" in rg
    # expected generation must be below nameplate (CFs < 1)
    assert rg["effective_renewable_mw"] < rg["renewable_mw"]
    # load_coverage is derived from expected generation, not nameplate
    expected = ls.score_load_coverage(rg["effective_renewable_mw"], rg["effective_demand_mw"])
    assert result["scores"]["load_coverage"] == expected
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_location_scorer.py::test_analyze_location_coverage_uses_expected_generation -q`
Expected: FAIL (`KeyError: 'effective_renewable_mw'` or load_coverage mismatch).

- [ ] **Step 3: Wire expected generation into the coverage block**

In `analyze_location`, replace step 6 (currently):

```python
    # 6. Load-coverage score: actual regional renewable capacity vs. DC total demand.
    #    Uses effective demand (= dc_capacity × PUE), which includes cooling overhead.
    coverage_ratio_pct = (
        regional_stats["renewable_mw"] / effective_demand_mw * 100
        if effective_demand_mw > 0 else 0.0
    )
    s_load_coverage = score_load_coverage(regional_stats["renewable_mw"], effective_demand_mw)
```

with:

```python
    # 6. Load-coverage score: expected regional renewable *generation* vs. DC total demand.
    #    Nameplate capacity is weighted by per-fuel capacity factors (Solar/Wind
    #    weather-derived; others static) before comparing to effective demand
    #    (= dc_capacity × PUE, including cooling overhead).
    effective_renewable_mw = expected_generation_mw(
        regional_stats["fuel_mw"], avg_irr, avg_wind
    )
    coverage_ratio_pct = (
        effective_renewable_mw / effective_demand_mw * 100
        if effective_demand_mw > 0 else 0.0
    )
    s_load_coverage = score_load_coverage(effective_renewable_mw, effective_demand_mw)
```

In the `regional_grid` dict, add `effective_renewable_mw` (after `renewable_mw`) and switch `coverage_possible` to expected generation:

```python
        "renewable_mw": round(regional_stats["renewable_mw"], 1),
        "effective_renewable_mw": round(effective_renewable_mw, 1),
```

```python
        "coverage_possible": effective_renewable_mw >= effective_demand_mw,
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_location_scorer.py -q`
Expected: PASS (existing tests + new one).

- [ ] **Step 5: Full suite + commit**

Run: `.venv/bin/python -m pytest -q` → Expected: all pass.
If `config/default_config.yaml` shows modified, revert it: `git checkout -- config/default_config.yaml`.

```bash
git add backend/twin/location_scorer.py tests/test_location_scorer.py
git commit -m "feat: base load coverage on expected renewable generation (#3)"
```

---

### Task 3: Frontend — coverage numerator + expected-generation display

**Files:**
- Modify: `frontend/src/main.js` (`updateAllDerivedValues`, `renderRegionalMixChart`)
- Modify: `frontend/index.html` (regional grid labels)

**Interfaces:**
- Consumes: `regional_grid.effective_renewable_mw` (Task 2).

- [ ] **Step 1: Use expected generation as the coverage numerator in `updateAllDerivedValues`**

In `frontend/src/main.js`, inside the `for (const loc of state.locations)` loop, change the numerator from nameplate to expected generation. Replace:

```js
    const renMw = loc.regional_grid?.renewable_mw ?? 0;
    const effMw = dcMw * pue;                       // total facility demand incl. cooling
    const covPct = effMw > 0 ? renMw / effMw * 100 : 0;
```

with:

```js
    const renGenMw = loc.regional_grid?.effective_renewable_mw ?? 0;  // CF-weighted, slider-independent
    const effMw = dcMw * pue;                       // total facility demand incl. cooling
    const covPct = effMw > 0 ? renGenMw / effMw * 100 : 0;
```

And replace the `coverage_possible` line:

```js
    loc.regional_grid.coverage_possible = renGenMw >= effMw;
```

(Leave the `effective_demand_mw`, `coverage_ratio_pct`, `load_coverage`, and suitability-recompute lines unchanged.)

- [ ] **Step 2: Add the expected-generation label to index.html**

In `frontend/index.html`, change the bar header text (line ~211) from `<span>Renewable vs. IT Load</span>` to `<span>Expected gen. vs. demand</span>`, and add a nameplate context line after the labels row. Replace:

```html
                <div style="display:flex;justify-content:space-between;margin-top:6px;font-size:11px;color:#64748b">
                  <span id="regional-ren-label">—</span>
                  <span id="regional-it-label">—</span>
                </div>
```

with:

```html
                <div style="display:flex;justify-content:space-between;margin-top:6px;font-size:11px;color:#64748b">
                  <span id="regional-ren-label">—</span>
                  <span id="regional-it-label">—</span>
                </div>
                <div id="regional-nameplate-label" style="margin-top:2px;font-size:10px;color:#94a3b8">—</div>
```

- [ ] **Step 3: Update `renderRegionalMixChart` labels in main.js**

Replace the existing label assignments:

```js
  document.getElementById('regional-ren-label').textContent =
    `${Math.round(rg.renewable_mw).toLocaleString()} MW renewable`;
  document.getElementById('regional-it-label').textContent =
    `${Math.round(rg.effective_demand_mw).toLocaleString()} MW needed`;
```

with:

```js
  document.getElementById('regional-ren-label').textContent =
    `≈ ${Math.round(rg.effective_renewable_mw).toLocaleString()} MW expected`;
  document.getElementById('regional-it-label').textContent =
    `${Math.round(rg.effective_demand_mw).toLocaleString()} MW needed`;
  document.getElementById('regional-nameplate-label').textContent =
    `${Math.round(rg.renewable_mw).toLocaleString()} MW installed (nameplate)`;
```

- [ ] **Step 4: Verify build**

Run: `cd frontend && npm run build`
Expected: build succeeds, no errors.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/main.js frontend/index.html
git commit -m "feat: show expected generation and base coverage bar on it (#3)"
```

---

### Task 4: Documentation

**Files:**
- Modify: `CLAUDE.md`
- Modify: `/Users/kbecker/.claude/projects/-Users-kbecker-projects-Master-DigitalTwin-Digital-Twin-Renewable-Data-Center/memory/MEMORY.md`

- [ ] **Step 1: Update CLAUDE.md**

In `CLAUDE.md`, find the line in the "Scoring — two distinct metrics" section that reads:

```
Load-coverage compares regional renewable capacity to `effective_demand_mw`
(IT load × PUE, i.e. including cooling).
```

Replace it with:

```
Load-coverage compares regional renewable **expected generation** (nameplate ×
per-fuel capacity factor; Solar/Wind weather-derived, others static) to
`effective_demand_mw` (IT load × PUE, i.e. including cooling).
```

- [ ] **Step 2: Update MEMORY.md**

In the memory `MEMORY.md`, find the same "Load-coverage compares regional renewable capacity to `effective_demand_mw`" wording in the scoring section and replace it with the expected-generation wording from Step 1.

- [ ] **Step 3: Commit (repo doc only)**

```bash
git add CLAUDE.md
git commit -m "docs: load coverage now uses expected generation (#3)"
```

---

## Self-Review

**Spec coverage:**
- CF model (solar/wind/static) → Task 1 ✓
- `expected_generation_mw` pure function → Task 1 ✓
- Integration into load-coverage + `effective_renewable_mw` in regional_grid → Task 2 ✓
- Frontend numerator + display → Task 3 ✓
- Docs → Task 4 ✓
- Scope guard: grid score & fuel-mix chart untouched (Task 2 only changes coverage lines) ✓

**Placeholder scan:** No TBD/TODO; all code shown.

**Type consistency:** `solar_capacity_factor`/`wind_capacity_factor`/`expected_generation_mw`, `effective_renewable_mw`, `regional-nameplate-label` used consistently across tasks.

## Out of scope
- #2 grid-score double-counting, #6 heatmap rate limit, temporal matching/storage.
