# Design Spec: Zwei klar benannte Scoring-Metriken

**Datum:** 2026-06-18
**Branch:** `feature/scoring-fixes`
**Scope:** Findings #1 (Umbenennung), #4 (Doku), #5 (PUE-Fix)

## Problem

Die App berechnet zwei völlig verschiedene "Composite"-Scores, die beide
gleich heißen und sich systematisch widersprechen können:

- **Heatmap-Overlay** (`compute_grid`): `composite = 60% Solar + 40% Wind`,
  rein wetterbasiert (Open-Meteo).
- **Klick-Analyse** (`analyze_location`): `composite = 40% Grid + 35% Load-Coverage
  + 25% Climate`, basiert auf regionalen Kraftwerksdaten (WRI).

Ein Nutzer sieht die Heatmap nach Solar+Wind eingefärbt, klickt einen Punkt an
und erhält einen Score, der von ganz anderen Faktoren getrieben wird. Beide
heißen "Composite" — irreführend für Nutzer und in einer Forschungsarbeit
angreifbar.

Zusätzlich (#5): Die Lastdeckung vergleicht die regionale EE-Leistung gegen die
reine IT-Last (`dc_capacity_mw`) statt gegen den Gesamtbedarf inklusive Kühlung
(`effective_demand_mw = dc_capacity_mw × PUE`).

## Entscheidung

Die beiden Metriken bleiben bewusst getrennt, werden aber eindeutig benannt.
Das Wort "Composite" verschwindet aus UI und API.

| Metrik | Bedeutung | Formel | Backend-Key | UI-Label |
|---|---|---|---|---|
| **Renewable Potential** | Heatmap, reine EE-Ressource | 60% Solar + 40% Wind | `potential` | "Renewable Potential" |
| **Site Suitability** | Klick, RZ-Eignung inkl. Netz/Kühlung | 40% Grid + 35% Load-Coverage + 25% Climate | `suitability` | "Site Suitability" |

## Änderungen

### #1 — Umbenennung

**Backend**
- `backend/twin/heatmap.py`: Return-Key `"composite"` → `"potential"`
  (interne Variable `comp_row`/`composite` analog umbenennen).
- `backend/twin/location_scorer.py`: `scores.composite` → `scores.suitability`
  im Return-Dict von `analyze_location`; interne Variable `composite` → `suitability`;
  `_recommendation`-Parameter analog.

**Frontend**
- `frontend/src/heatmap.js`: `g.composite` → `g.potential` (2 Stellen).
- `frontend/src/main.js`: alle Lesezugriffe `s.composite` / `scores.composite`
  → `s.suitability` / `scores.suitability` (~10 Stellen, inkl. Marker-Icon,
  Gauge, Vergleichsansicht, Tabelle); Label-Text `"Composite: …/100"`
  → `"Site Suitability: …/100"`; Tabellen-Header `<th>Composite</th>`
  → `<th>Site Suitability</th>`.
- `frontend/index.html`: Kommentar an der Gauge und ggf. Heatmap-Legenden-Titel
  auf "Renewable Potential" anpassen.

**Tests**
- Bestehende Tests referenzieren `composite` nicht → kein Bruch.
- Optional: ein Assert auf den neuen Key `scores.suitability` ergänzen
  (kein Live-API-Call, nur Struktur).

### #5 — PUE-Fix in `analyze_location`

`effective_demand_mw` wird bereits berechnet (= `dc_capacity_mw × PUE`).

- `coverage_ratio_pct`: Nenner `dc_capacity_mw` → `effective_demand_mw`.
- `regional_grid.coverage_possible`: `renewable_mw >= dc_capacity_mw`
  → `renewable_mw >= effective_demand_mw`.
- `regional_grid`: zusätzliches Feld `effective_demand_mw` ausweisen,
  damit die angezeigte Zahl zum Score passt. `it_load_mw` bleibt als
  Informationsfeld erhalten.
- Frontend zeigt im Regional-Grid-Block beide Werte: IT-Last und effektiver
  Bedarf (inkl. Kühlung).

**Effekt:** Site-Suitability-Scores sinken leicht und realistisch, weil der
Kühlbedarf in die Lastdeckung eingeht.

### #4 — Doku

- `CLAUDE.md`: Abschnitt "Scoring Weights" durch die Zwei-Metriken-Tabelle oben
  ersetzen; klarstellen, dass Heatmap und Klick verschiedene Dinge messen.
- Memory (`MEMORY.md` + Scoring-Memory-Datei): auf zwei Metriken aktualisieren;
  veraltetes "28% solar + 28% wind + 24% climate + 20% grid" entfernen.

## Nicht in diesem Scope (Folge-Branches)

- #2 Doppelzählung Grid + Load-Coverage (75% des Suitability-Scores aus einer Variable).
- #3 Nameplate vs. Kapazitätsfaktor bei der Lastdeckung.
- #6 Open-Meteo-Rate-Limit der Heatmap (~49 Abrufe pro Viewport).

## Verifikation

- `pytest -q` bleibt grün (7 Tests).
- App startet, Heatmap rendert (`grid.potential`), Klick-Panel zeigt
  "Site Suitability", Vergleichstabelle und Marker nutzen den neuen Key.
- Keine verbleibenden Vorkommen von `composite`/`Composite` in `frontend/`,
  `backend/twin/heatmap.py`, `backend/twin/location_scorer.py`.
