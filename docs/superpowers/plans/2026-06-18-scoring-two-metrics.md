# Two Clearly-Named Scoring Metrics — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the single ambiguous "Composite" score with two distinctly-named metrics — `potential` (heatmap, weather-based) and `suitability` (click, site-based) — and fix load-coverage to use effective facility demand (incl. PUE).

**Architecture:** Pure rename across backend + frontend with no behavioural change to the heatmap formula; a small load-coverage correction (#5) applied consistently in BOTH the backend (`analyze_location`) and the frontend client-side recompute (`updateAllDerivedValues`), since the frontend overrides backend coverage values on slider changes.

**Tech Stack:** Python 3.13 / FastAPI / pytest (backend), vanilla JS / Vite / Leaflet (frontend).

## Global Constraints

- The word "Composite"/"composite" must not remain in `frontend/`, `backend/twin/heatmap.py`, or `backend/twin/location_scorer.py` after this work.
- Backend keys: heatmap grid score = `potential`; click score = `suitability`.
- UI labels: heatmap = "Renewable Potential"; click = "Site Suitability".
- Load-coverage denominator = `effective_demand_mw` (= `dc_capacity_mw × PUE`), applied identically in backend and frontend.
- Tests run with `.venv/bin/python -m pytest -q` from project root. No live network in tests — patch weather/geocode/plant functions.
- Frontend has no JS test runner; verify with `npm run build` + grep.

---

### Task 1: Backend — load-coverage helper, PUE fix, `suitability` rename

**Files:**
- Modify: `backend/twin/location_scorer.py` (`analyze_location`, new helper, `_recommendation`)
- Test: `tests/test_location_scorer.py` (create)

**Interfaces:**
- Produces: `score_load_coverage(renewable_mw: float, effective_demand_mw: float) -> float` (0–100, capped, rounded to 1 dp).
- Produces: `analyze_location(...)["scores"]["suitability"]` (was `composite`); `analyze_location(...)["regional_grid"]["effective_demand_mw"]` (new).

- [ ] **Step 1: Write the failing tests**

Create `tests/test_location_scorer.py`:

```python
from backend.twin import location_scorer as ls


def test_score_load_coverage_uses_effective_demand():
    assert ls.score_load_coverage(100.0, 50.0) == 100.0   # capped at 100
    assert ls.score_load_coverage(50.0, 100.0) == 50.0
    assert ls.score_load_coverage(50.0, 0.0) == 0.0        # guard against div-by-zero


def _fake_weather(lat, lng, days=7):
    n = 168
    return {"hourly": {
        "temperature_2m": [5.0] * n,
        "windspeed_10m": [8.0] * n,
        "direct_radiation": [150.0] * n,
        "diffuse_radiation": [50.0] * n,
        "cloudcover": [0.0] * n,
        "precipitation": [0.0] * n,
        "time": ["2026-06-18T00:00"] * n,
    }}


def test_analyze_location_renames_to_suitability_and_uses_effective_demand(monkeypatch):
    monkeypatch.setattr(ls, "get_location_info",
                        lambda lat, lng: {"city": "X", "country": "Y",
                                          "country_code": "DE", "display": "X, Y"})
    monkeypatch.setattr(ls, "fetch_weather_forecast", _fake_weather)
    monkeypatch.setattr(ls, "get_regional_plant_stats",
                        lambda lat, lng: {"fuel_mw": {"Solar": 500.0, "Wind": 300.0},
                                          "total_mw": 1000.0, "renewable_mw": 800.0,
                                          "plant_count": 5, "top_plants": []})
    result = ls.analyze_location(0.0, 0.0, servers=1000, ai_intensity=0.5)

    assert "suitability" in result["scores"]
    assert "composite" not in result["scores"]
    assert "effective_demand_mw" in result["regional_grid"]
    # coverage uses effective demand (= dc_capacity * PUE), not raw IT load
    eff = result["regional_grid"]["effective_demand_mw"]
    expected = round(min(100.0, 800.0 / eff * 100), 1)
    assert result["scores"]["load_coverage"] == expected
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_location_scorer.py -q`
Expected: FAIL (`AttributeError: module ... has no attribute 'score_load_coverage'`).

- [ ] **Step 3: Add the `score_load_coverage` helper**

In `backend/twin/location_scorer.py`, immediately after `score_grid_regional` (around line 131), add:

```python
def score_load_coverage(renewable_mw: float, effective_demand_mw: float) -> float:
    """Load-coverage score 0–100: regional renewable capacity vs. total facility
    demand (IT load × PUE, i.e. including cooling overhead)."""
    if effective_demand_mw <= 0:
        return 0.0
    return round(min(100.0, renewable_mw / effective_demand_mw * 100), 1)
```

- [ ] **Step 4: Wire it into `analyze_location` + rename `composite` → `suitability`**

In `analyze_location`, replace the load-coverage block (step 6, currently):

```python
    coverage_ratio_pct = (
        regional_stats["renewable_mw"] / dc_capacity_mw * 100
        if dc_capacity_mw > 0 else 0.0
    )
    s_load_coverage = round(min(100.0, coverage_ratio_pct), 1)
```

with:

```python
    coverage_ratio_pct = (
        regional_stats["renewable_mw"] / effective_demand_mw * 100
        if effective_demand_mw > 0 else 0.0
    )
    s_load_coverage = score_load_coverage(regional_stats["renewable_mw"], effective_demand_mw)
```

Rename the composite variable + comment (step 7):

```python
    # 7. Site Suitability score – three dimensions for a grid-connected hyperscaler DC.
    # Grid renewable mix (40%) + actual load coverage (35%) + cooling climate (25%).
    suitability = round(
        s_grid            * 0.40
        + s_load_coverage * 0.35
        + s_climate       * 0.25,
        1,
    )
```

In the `regional_grid` dict, change `coverage_possible` and add `effective_demand_mw`:

```python
        "it_load_mw": round(dc_capacity_mw, 1),
        "effective_demand_mw": round(effective_demand_mw, 1),
        "coverage_ratio_pct": round(coverage_ratio_pct, 1),
        "coverage_possible": regional_stats["renewable_mw"] >= effective_demand_mw,
```

Update the `_recommendation` call and the `scores` dict:

```python
    label, recommendation = _recommendation(suitability, s_climate, s_grid, s_load_coverage)
```

```python
        "scores": {
            "climate": s_climate,
            "grid": s_grid,
            "load_coverage": s_load_coverage,
            "suitability": suitability,
            "label": label,
        },
```

Rename the first parameter of `_recommendation` from `composite` to `suitability` (signature + the `if suitability >= 80:` comparisons in its body).

- [ ] **Step 5: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_location_scorer.py -q`
Expected: PASS (3 tests).

- [ ] **Step 6: Confirm no `composite` remains in the file & full suite green**

Run: `grep -n composite backend/twin/location_scorer.py` → Expected: no output.
Run: `.venv/bin/python -m pytest -q` → Expected: all pass (10 tests).
If `config/default_config.yaml` shows as modified afterwards, revert it: `git checkout -- config/default_config.yaml` (known non-isolated test side-effect).

- [ ] **Step 7: Commit**

```bash
git add backend/twin/location_scorer.py tests/test_location_scorer.py
git commit -m "feat: rename click score to suitability, coverage vs effective demand (#1,#5)"
```

---

### Task 2: Backend — heatmap `composite` → `potential`

**Files:**
- Modify: `backend/twin/heatmap.py` (`compute_grid` return dict + local var)
- Test: `tests/test_heatmap.py` (create)

**Interfaces:**
- Produces: `compute_grid(...)["potential"]` (was `composite`); still returns `solar`, `wind`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_heatmap.py`:

```python
from backend.twin import heatmap


def test_compute_grid_returns_potential_not_composite(monkeypatch):
    monkeypatch.setattr(heatmap, "_fetch_point",
                        lambda lat, lng: {"avg_temp": 10.0, "avg_wind": 8.0, "avg_irr": 200.0})
    grid = heatmap.compute_grid(north=1.0, south=0.0, east=1.0, west=0.0, resolution=0.5)
    assert "potential" in grid
    assert "composite" not in grid
    assert "solar" in grid and "wind" in grid
    assert len(grid["potential"]) == grid["rows"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_heatmap.py -q`
Expected: FAIL (`assert 'potential' in grid`).

- [ ] **Step 3: Rename in `compute_grid`**

In `backend/twin/heatmap.py`, rename the local accumulator and the return key. Replace `composite: list[list[float]] = []` → `potential: list[list[float]] = []`; `comp_row` → `pot_row`; `comp_row.append(...)` → `pot_row.append(...)`; `composite.append(comp_row)` → `potential.append(pot_row)`; and in the return dict `"composite": composite,` → `"potential": potential,`.

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_heatmap.py -q`
Expected: PASS.

- [ ] **Step 5: Confirm no `composite` remains & commit**

Run: `grep -n composite backend/twin/heatmap.py` → Expected: no output.

```bash
git add backend/twin/heatmap.py tests/test_heatmap.py
git commit -m "feat: rename heatmap grid score to potential (#1)"
```

---

### Task 3: Frontend — rename + #5 client-side recompute + labels

**Files:**
- Modify: `frontend/src/heatmap.js` (grid key read)
- Modify: `frontend/src/main.js` (score property reads, `updateAllDerivedValues`, labels, table header)
- Modify: `frontend/index.html` (comment / legend title if present)

**Interfaces:**
- Consumes: `grid.potential` (Task 2), `scores.suitability` + `regional_grid.effective_demand_mw` (Task 1).

- [ ] **Step 1: Rename grid key in heatmap.js**

In `frontend/src/heatmap.js`, replace both occurrences of `.composite` with `.potential` (lines ~131 `if (!g || !g.potential) return;` and ~133 `const grid = g.potential;`).

- [ ] **Step 2: Rename score property reads in main.js**

In `frontend/src/main.js`, replace all `.composite` property accesses with `.suitability` (affects `loc.scores`, `s.`, `locData.scores`, `result.scores` — ~12 occurrences). Do NOT touch display strings yet.

- [ ] **Step 3: Fix display strings in main.js**

Replace the badge label:

```js
    <span class="badge-label">Site Suitability: ${s.suitability}/100</span>
```

(was `Composite: ${s.composite}/100`). Replace the comparison-table header `<th>Composite</th>` → `<th>Site Suitability</th>`.

- [ ] **Step 4: Apply #5 fix + suitability recompute in `updateAllDerivedValues`**

Replace the loop body (lines ~109–123) with:

```js
    const pue = estimatePue(loc.weather.avg_temperature_c);
    const renMw = loc.regional_grid?.renewable_mw ?? 0;
    const effMw = dcMw * pue;                       // total facility demand incl. cooling
    const covPct = effMw > 0 ? renMw / effMw * 100 : 0;

    loc.energy.dc_it_capacity_mw = Math.round(dcMw * 10) / 10;
    loc.energy.estimated_pue = Math.round(pue * 100) / 100;
    loc.energy.effective_demand_mw = Math.round(effMw * 10) / 10;
    loc.regional_grid.it_load_mw = Math.round(dcMw * 10) / 10;
    loc.regional_grid.effective_demand_mw = Math.round(effMw * 10) / 10;
    loc.regional_grid.coverage_ratio_pct = Math.round(covPct * 10) / 10;
    loc.regional_grid.coverage_possible = renMw >= effMw;
    loc.scores.load_coverage = Math.round(Math.min(100, covPct) * 10) / 10;
    // Site Suitability depends on load_coverage (35%) — recompute so it reflects slider changes
    loc.scores.suitability = Math.round(
      (loc.scores.grid * 0.40 + loc.scores.load_coverage * 0.35 + loc.scores.climate * 0.25) * 10
    ) / 10;

    // Refresh marker if this location is on the map
    const marker = state.markers.get(loc._id);
    if (marker) marker.setIcon(createMarkerIcon(loc.scores.suitability));
```

- [ ] **Step 5: Update regional-grid coverage labels in `renderRegionalMixChart`**

The coverage now measures effective demand, so the "needed" figure and badge text must match. Replace lines ~415–416:

```js
  document.getElementById('regional-it-label').textContent =
    `${Math.round(rg.effective_demand_mw).toLocaleString()} MW needed`;
```

And the badge success text (~421):

```js
    badge.textContent = '✓ Renewable capacity covers facility demand';
```

- [ ] **Step 6: Update index.html**

In `frontend/index.html`, change the gauge comment `<!-- Composite score gauge -->` → `<!-- Site Suitability score gauge -->`. If a heatmap legend title element contains "Composite", change it to "Renewable Potential".

- [ ] **Step 7: Verify build + no residual composite**

Run: `cd frontend && npm run build` → Expected: build succeeds, no errors.
Run (from project root): `grep -rn "composite\|Composite" frontend/src frontend/index.html` → Expected: no output.

- [ ] **Step 8: Commit**

```bash
git add frontend/src/heatmap.js frontend/src/main.js frontend/index.html
git commit -m "feat: rename UI to Renewable Potential / Site Suitability, fix coverage vs effective demand (#1,#5)"
```

---

### Task 4: Documentation (#4)

**Files:**
- Modify: `CLAUDE.md` (Scoring Weights section)
- Modify: `/Users/kbecker/.claude/projects/-Users-kbecker-projects-Master-DigitalTwin-Digital-Twin-Renewable-Data-Center/memory/MEMORY.md`
- Modify: the scoring memory file referenced from MEMORY.md (if one exists)

- [ ] **Step 1: Update CLAUDE.md**

Replace the `### Scoring Weights` section content with:

```markdown
### Scoring — two distinct metrics
The app computes two *different* metrics; neither is called "Composite".
- **Renewable Potential** (heatmap overlay, `compute_grid` → key `potential`):
  weather-based resource quality = 60% solar + 40% wind.
- **Site Suitability** (click analysis, `analyze_location` → key `suitability`):
  site fitness for a grid-connected DC = 40% grid + 35% load-coverage + 25% climate.
Load-coverage compares regional renewable capacity to `effective_demand_mw`
(IT load × PUE, i.e. including cooling).
```

- [ ] **Step 2: Update MEMORY.md and the scoring memory file**

In the memory directory, replace any "28% solar + 28% wind + 24% climate + 20% grid" wording with the two-metric description above. Update the `## Scoring Dimensions` block in MEMORY.md to list the two metrics and their keys (`potential`, `suitability`).

- [ ] **Step 3: Commit (repo docs only — memory files are outside the repo)**

```bash
git add CLAUDE.md
git commit -m "docs: describe two scoring metrics, drop stale composite weights (#4)"
```

---

## Self-Review

**Spec coverage:**
- #1 rename: heatmap key (Task 2), click key + all frontend reads (Tasks 1, 3) ✓
- #4 docs: CLAUDE.md + memory (Task 4) ✓
- #5 PUE fix: backend `analyze_location` (Task 1) + frontend `updateAllDerivedValues` + labels (Task 3) ✓
- Discovered during planning: frontend recomputes coverage client-side and never recomputed the score → fixed in Task 3 Step 4 (justified: the #5 fix is invisible otherwise). Flag to user.

**Placeholder scan:** No TBD/TODO; all code shown.

**Type consistency:** `potential` (heatmap), `suitability` (click), `effective_demand_mw`, `score_load_coverage(renewable_mw, effective_demand_mw)` used consistently across tasks.

## Out of scope (follow-up branches)
- #2 double-counting (grid + load-coverage), #3 capacity factor, #6 Open-Meteo rate limit.
