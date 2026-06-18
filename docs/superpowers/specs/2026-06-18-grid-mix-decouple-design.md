# Design Spec: Decouple Grid Score from Load Coverage (#2)

**Datum:** 2026-06-18
**Branch:** `feature/grid-mix-decouple`
**Scope:** Finding #2 — Doppelzählung Grid + Load-Coverage

## Problem

`score_grid_regional` = `fraction*50 + capacity_score*50`, wobei `capacity_score`
die log-skalierte absolute `renewable_mw` ist. Die Load-Coverage basiert ebenfalls
auf der regionalen erneuerbaren Kapazität. Dadurch werden ~75 % des
Site-Suitability-Scores (Grid 40 % + Load-Coverage 35 %) faktisch von **einer**
Variable (regionale Erneuerbare) getrieben — die drei Gewichte suggerieren mehr
Unabhängigkeit, als real besteht.

## Entscheidung

Der absolute Kapazitätsterm wird aus dem Grid-Score **entfernt**. Der Grid-Score
misst dann ausschließlich die **Sauberkeit des regionalen Mix** (erneuerbarer Anteil):

```
score_grid_regional(renewable_mw, total_mw):
    fraction = renewable_mw / total_mw  if total_mw > 0 else 0.0
    return round(fraction * 100, 1)
```

Damit sind die drei Dimensionen entkoppelt:
- **Grid** = erneuerbarer Anteil am regionalen Mix (Sauberkeit), lastunabhängig.
- **Load-Coverage** = CF-gewichtete erwartete Erzeugung vs. RZ-Bedarf (absolut).
- **Climate** = Kühlung.

Eine kleine, zu 100 % erneuerbare Region erhält damit einen hohen Grid-Score, aber
ggf. eine niedrige Load-Coverage — das gewünschte, differenzierte Verhalten.

**Konsequenz:** Der Grid-Score ist nun identisch mit dem bereits ausgegebenen
`regional_grid.renewable_fraction_pct` (beide = `fraction*100`). Score-Bar und
angezeigter EE-Anteil stimmen damit überein.

## Entscheidungen (vom Nutzer bestätigt)
- **Gewichte 40/35/25 bleiben** unverändert (relative Wichtigkeit unverändert).
- **UI-Label „Grid" → „Renewable Mix"** (Backend-Key `grid` bleibt).

## Komponenten

### Backend (`backend/twin/location_scorer.py`)
- `score_grid_regional`: Body auf `round(fraction*100, 1)` reduzieren, Docstring
  anpassen. Signatur unverändert. Keine weiteren Aufrufstellen betroffen
  (Aufruf in `analyze_location` bleibt gleich).

### Frontend
- `frontend/index.html:167`: Score-Bar-Label `<span class="score-bar-name">Grid</span>`
  → `Renewable Mix`.
- `frontend/src/main.js`: Vergleichschart-Dataset-Label `'Grid'` → `'Renewable Mix'`;
  Vergleichstabellen-Header `⚡ Grid` → `⚡ Renewable Mix`.
- **Nicht** ändern: die Sektion „Regional Grid" (eigener Bereich) und der
  Coverage-Badge-Text „Grid backup required" (anderer Kontext).

### Doku
- `CLAUDE.md` + Memory: Grid-Dimension als „erneuerbarer Anteil am regionalen Mix
  (Sauberkeit)" beschreiben; klarstellen, dass die absolute Kapazität allein über
  Load-Coverage einfließt (keine Doppelzählung mehr).

## Tests
- `score_grid_regional`: `800/1000 → 80.0`; `total_mw=0 → 0.0`; voll erneuerbar → 100.0.
- Entkopplungs-Test (monkeypatched `analyze_location`): kleine, zu 100 % erneuerbare
  Region (z.B. `renewable_mw=50`, `total_mw=50`) mit großer DC-Last → `scores.grid == 100`
  **und** `scores.load_coverage < 100` (Grid hoch, Deckung niedrig).

## Nicht in diesem Scope
- #6 Heatmap-Rate-Limit.
- Erneute Kalibrierung der Gewichte oder CF-Werte.
- Grid-Reliability/CO₂-Intensität aus externen Quellen.

## Verifikation
- `.venv/bin/python -m pytest -q` grün.
- App: Grid-Bar zeigt denselben Wert wie der regionale EE-Anteil; Label „Renewable Mix";
  Load-Coverage unverändert.
