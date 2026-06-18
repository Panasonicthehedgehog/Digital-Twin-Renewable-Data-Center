# Decouple Grid Score from Load Coverage Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the Grid score measure only the regional renewable *share* (cleanliness), removing the absolute-capacity term that duplicates load-coverage, so Site Suitability's three dimensions are genuinely independent.

**Architecture:** A one-function change in `score_grid_regional` (drop the log-scaled capacity term, keep the renewable fraction × 100), plus UI label changes ("Grid" → "Renewable Mix") and docs. Weights stay 40/35/25; backend key stays `grid`.

**Tech Stack:** Python 3.13 / FastAPI / pytest (backend), vanilla JS / Vite (frontend).

## Global Constraints

- `score_grid_regional(renewable_mw, total_mw)` returns `round(fraction * 100, 1)` where `fraction = renewable_mw/total_mw` (0.0 if `total_mw <= 0`). No capacity term.
- Signature unchanged; the call site in `analyze_location` is untouched.
- Suitability weights stay 40 (grid) / 35 (load-coverage) / 25 (climate).
- UI label "Grid" → "Renewable Mix" in the score bar, comparison chart dataset, and comparison table header. Do NOT change the "Regional Grid" section title or the "Grid backup required" coverage badge.
- Tests: `.venv/bin/python -m pytest -q` from project root, no live network (monkeypatch `get_location_info`, `fetch_weather_forecast`, `get_regional_plant_stats`).
- Known quirk: a non-isolated config test may dirty `config/default_config.yaml`. If modified after the full suite, revert with `git checkout -- config/default_config.yaml` — never stage it.
- Commit messages must NOT contain a Co-Authored-By trailer.

---

### Task 1: Grid score = renewable fraction only

**Files:**
- Modify: `backend/twin/location_scorer.py` (`score_grid_regional`, ~lines 123–131)
- Test: `tests/test_location_scorer.py` (add tests; reuse existing `_fake_weather`)

**Interfaces:**
- `score_grid_regional(renewable_mw: float, total_mw: float) -> float` — now returns `fraction*100` rounded 1 dp.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_location_scorer.py`:

```python
def test_score_grid_regional_is_renewable_fraction():
    assert ls.score_grid_regional(800.0, 1000.0) == 80.0
    assert ls.score_grid_regional(50.0, 50.0) == 100.0      # fully renewable
    assert ls.score_grid_regional(0.0, 0.0) == 0.0          # no plants -> guard


def test_grid_and_coverage_are_decoupled(monkeypatch):
    # Small but 100% renewable region + large DC: grid high, coverage low.
    monkeypatch.setattr(ls, "get_location_info",
                        lambda lat, lng: {"city": "X", "country": "Y",
                                          "country_code": "DE", "display": "X, Y"})
    monkeypatch.setattr(ls, "fetch_weather_forecast", _fake_weather)
    monkeypatch.setattr(ls, "get_regional_plant_stats",
                        lambda lat, lng: {"fuel_mw": {"Solar": 50.0},
                                          "total_mw": 50.0, "renewable_mw": 50.0,
                                          "plant_count": 1, "top_plants": []})
    result = ls.analyze_location(0.0, 0.0, servers=200_000, ai_intensity=0.7)
    assert result["scores"]["grid"] == 100.0
    assert result["scores"]["load_coverage"] < 100.0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_location_scorer.py::test_score_grid_regional_is_renewable_fraction tests/test_location_scorer.py::test_grid_and_coverage_are_decoupled -q`
Expected: FAIL (current grid score adds the capacity term, so `score_grid_regional(800,1000)` ≠ 80.0 and the decoupling assertion on grid==100 fails).

- [ ] **Step 3: Reduce `score_grid_regional` to the renewable fraction**

In `backend/twin/location_scorer.py`, replace:

```python
def score_grid_regional(renewable_mw: float, total_mw: float) -> float:
    """Grid score 0–100 derived from actual regional plant data.

    50 pts for renewable fraction + 50 pts for absolute renewable capacity
    (log-scaled, ceiling at 100 GW).
    """
    fraction = renewable_mw / total_mw if total_mw > 0 else 0.0
    capacity_score = min(50.0, math.log1p(renewable_mw) / math.log1p(100_000.0) * 50.0)
    return round(fraction * 50.0 + capacity_score, 1)
```

with:

```python
def score_grid_regional(renewable_mw: float, total_mw: float) -> float:
    """Grid score 0–100 = renewable share of the regional generation mix.

    Measures only how clean the regional mix is (renewable fraction × 100).
    Absolute renewable capacity is intentionally NOT scored here — sufficiency
    for the specific datacenter load is captured separately by load-coverage,
    keeping the two Site-Suitability dimensions independent (no double-counting).
    """
    fraction = renewable_mw / total_mw if total_mw > 0 else 0.0
    return round(fraction * 100.0, 1)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_location_scorer.py -q`
Expected: PASS (existing tests + 2 new).

- [ ] **Step 5: Full suite + check unused import**

Run: `.venv/bin/python -m pytest -q` → Expected: all pass.
`math` is still used elsewhere in the module (haversine, capacity factors) — do NOT remove the `import math`. Confirm with: `grep -n "math\." backend/twin/location_scorer.py | head` (expect matches outside `score_grid_regional`).
If `config/default_config.yaml` shows modified, revert: `git checkout -- config/default_config.yaml`.

- [ ] **Step 6: Commit**

```bash
git add backend/twin/location_scorer.py tests/test_location_scorer.py
git commit -m "feat: grid score = renewable share only, decoupled from load coverage (#2)"
```

---

### Task 2: Frontend — rename "Grid" label to "Renewable Mix"

**Files:**
- Modify: `frontend/index.html` (score bar label, ~line 167)
- Modify: `frontend/src/main.js` (comparison chart dataset label ~line 543, comparison table header ~line 673)

**Interfaces:** Display-only; backend key `grid` unchanged.

- [ ] **Step 1: Rename the score-bar label in index.html**

In `frontend/index.html`, change `<span class="score-bar-name">Grid</span>` to:

```html
                <span class="score-bar-name">Renewable Mix</span>
```

- [ ] **Step 2: Rename the comparison chart dataset label in main.js**

In `frontend/src/main.js`, change the dataset label `{ label: 'Grid',          data: grid,      backgroundColor: '#8b5cf6' },` to:

```js
        { label: 'Renewable Mix',  data: grid,      backgroundColor: '#8b5cf6' },
```

- [ ] **Step 3: Rename the comparison table header in main.js**

In `frontend/src/main.js`, change `<th>⚡ Grid</th>` to:

```js
            <th>⚡ Renewable Mix</th>
```

(Leave `'✗ Grid backup required'` and the `<h4>Regional Grid …` title unchanged — different contexts.)

- [ ] **Step 4: Verify build + no stray "Grid" dimension label**

Run: `cd frontend && npm run build` → Expected: build succeeds.
Run (project root): `grep -n ">Grid<\|label: 'Grid'\|⚡ Grid" frontend/index.html frontend/src/main.js` → Expected: no output.

- [ ] **Step 5: Commit**

```bash
git add frontend/index.html frontend/src/main.js
git commit -m "feat: relabel Grid score dimension to Renewable Mix (#2)"
```

---

### Task 3: Documentation

**Files:**
- Modify: `CLAUDE.md`
- Modify: `/Users/kbecker/.claude/projects/-Users-kbecker-projects-Master-DigitalTwin-Digital-Twin-Renewable-Data-Center/memory/MEMORY.md`

- [ ] **Step 1: Update CLAUDE.md**

In `CLAUDE.md`, in the "Scoring — two distinct metrics" section, the Site Suitability bullet currently reads:

```
- **Site Suitability** (click analysis, `analyze_location` → key `suitability`):
  site fitness for a grid-connected DC = 40% grid + 35% load-coverage + 25% climate.
```

Replace the `40% grid` wording to clarify what grid now means, by changing that bullet to:

```
- **Site Suitability** (click analysis, `analyze_location` → key `suitability`):
  site fitness for a grid-connected DC = 40% grid + 35% load-coverage + 25% climate.
  "Grid" is the **renewable share** of the regional mix (cleanliness) only;
  absolute capacity sufficiency is captured solely by load-coverage (no double-counting).
```

- [ ] **Step 2: Update MEMORY.md**

In the memory `MEMORY.md`, in the scoring section, add the same clarifying sentence after the Site Suitability line: that "Grid" = renewable share of the regional mix (cleanliness) only, with absolute sufficiency handled by load-coverage. This file is OUTSIDE the git repo — save the edit, do NOT git-add it.

- [ ] **Step 3: Commit (repo doc only)**

```bash
git add CLAUDE.md
git commit -m "docs: clarify grid score is renewable share only (#2)"
```

---

## Self-Review

**Spec coverage:**
- Grid score → fraction only (Task 1) ✓
- Decoupling verified by test (Task 1) ✓
- Weights unchanged: no task touches the 0.40/0.35/0.25 line ✓
- UI label "Grid" → "Renewable Mix" (Task 2) ✓
- Docs (Task 3) ✓
- Scope guard: only `score_grid_regional` body changes in backend; call site, load-coverage, fuel-mix untouched ✓

**Placeholder scan:** No TBD/TODO; all code shown.

**Type consistency:** `score_grid_regional(renewable_mw, total_mw) -> float` unchanged signature; label string "Renewable Mix" consistent across Task 2 steps.

## Out of scope
- #6 heatmap rate limit; weight recalibration; external grid-reliability/CO₂ data.
