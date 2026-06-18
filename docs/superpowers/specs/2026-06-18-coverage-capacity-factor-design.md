# Design Spec: Capacity-Factor-Weighted Load Coverage (#3)

**Datum:** 2026-06-18
**Branch:** `feature/coverage-capacity-factor`
**Scope:** Finding #3 — Nameplate vs. Kapazitätsfaktor bei der Lastdeckung

## Problem

Die Lastdeckung (`score_load_coverage`) vergleicht die regionale erneuerbare
**Nennleistung** (`renewable_mw`) direkt mit dem RZ-Dauerbedarf (`effective_demand_mw`).
Nennleistung ≠ tatsächliche Erzeugung: reale Kapazitätsfaktoren liegen bei
PV ~10–25 %, Wind ~25–40 %. Die Deckung wird dadurch systematisch überschätzt
(„100 % gedeckt" ist zu optimistisch).

## Entscheidung

Die Nennleistung wird **pro Fuel-Typ** mit einem Kapazitätsfaktor (CF) in eine
erwartete mittlere Erzeugung umgerechnet, und die Lastdeckung nutzt diese
erwartete Erzeugung statt der Nennleistung.

**Hybrider CF-Ansatz** (vom Nutzer bestätigt):
- **Solar & Wind: wetterabgeleitet** aus der bereits geholten Prognose
  (`avg_irr`, `avg_wind`) — konsistent mit dem „current 7-day forecast"-Ansatz der App.
- **Übrige erneuerbare Fuels: statische Literaturwerte** (standortunabhängig,
  da dispatchbar/Grundlast und ohne Wetter-Signal).

**Wirkungsbereich (vom Nutzer bestätigt): nur die Lastdeckung.** Grid-Score
(Finding #2) und der Fuel-Mix-Chart bleiben auf Nennleistung (Reporting-Konvention).
Die erwartete Erzeugung wird zusätzlich als eigene Kennzahl angezeigt.

## CF-Modell

Alle Werte sind **vereinfachte, literaturbasierte Näherungen** und als solche
zu dokumentieren — bewusst tunebar.

### Solar (wetterabgeleitet)
```
solar_cf = min(0.40, avg_irr / 1000.0 * 0.80)
```
- `avg_irr` = mittlere Gesamteinstrahlung (W/m²) über die 7-Tage-Stundenreihe (inkl. Nacht).
- `/1000` normiert gegen STC-Nennbedingung (1000 W/m²); `× 0.80` = Performance-Ratio
  (System-/Inverterverluste); Cap 0,40.

### Wind (wetterabgeleitet, mit Höhenkorrektur)
```
v_hub = avg_wind * 1.4         # 10 m → ~100 m Nabenhöhe, Power-Law-Shear α≈0.14
wind_cf = power_curve(v_hub)
```
mit vereinfachter Power-Curve auf dem **Mittelwind** (Proxy, keine Zeitreihen-Integration):
```
v_hub <= 3.0           -> 0.0            # unter cut-in
3.0 < v_hub < 12.0     -> (v_hub-3)/9 * 0.55
12.0 <= v_hub <= 25.0  -> 0.55           # rated
v_hub > 25.0           -> 0.0            # cut-out
```

### Statische CFs (übrige erneuerbare Fuels)
| Fuel | CF |
|---|---|
| Hydro | 0.40 |
| Biomass | 0.60 |
| Geothermal | 0.80 |
| Wave and Tidal | 0.30 |

Fuels, die nicht in dieser Tabelle und nicht Solar/Wind sind, aber als erneuerbar
gelten, erhalten einen konservativen Default-CF von 0.40.

## Komponenten

### Neue reine Funktion (`backend/twin/location_scorer.py`)
```
expected_generation_mw(fuel_mw: dict[str, float], avg_irr: float, avg_wind: float) -> float
```
- Summiert über `fuel_mw` nur die **erneuerbaren** Fuels (`_RENEWABLE_FUELS`),
  gewichtet jeden mit seinem CF (Solar/Wind wetterabgeleitet, Rest statisch).
- Nicht-erneuerbare Fuels werden ignoriert.
- Reine Funktion, ohne Netzwerk → unittestbar.

Hilfsfunktionen (intern, ebenfalls rein, testbar):
`solar_capacity_factor(avg_irr)`, `wind_capacity_factor(avg_wind)`.

### Einbindung in `analyze_location`
- `effective_renewable_mw = expected_generation_mw(regional_stats["fuel_mw"], avg_irr, avg_wind)`
- `s_load_coverage = score_load_coverage(effective_renewable_mw, effective_demand_mw)`
- `coverage_ratio_pct` und `coverage_possible` ebenfalls auf `effective_renewable_mw`.
- `regional_grid` neues Feld `effective_renewable_mw` (gerundet, 1 dp); `renewable_mw`
  (Nennleistung) bleibt unverändert erhalten.

### Frontend (`frontend/src/main.js`)
- `updateAllDerivedValues`: Zähler der Coverage = `regional_grid.effective_renewable_mw`
  (statt `renewable_mw`). Der CF-gewichtete Output ist sliderunabhängig → konstant
  pro Standort; die Slider ändern nur den Bedarf (Nenner).
- `renderRegionalMixChart`: zusätzliche Anzeige „erwartete Erzeugung" (`effective_renewable_mw`)
  neben „… MW renewable" (Nennleistung) und „… MW needed".

## Tests
- `expected_generation_mw`: Solar skaliert mit `avg_irr`; Wind folgt der Power-Curve
  an den Stützpunkten (unter cut-in = 0, im Rampenbereich, rated, über cut-out = 0);
  statische Fuels korrekt gewichtet; nicht-erneuerbare ignoriert; leeres Dict → 0.
- `solar_capacity_factor` / `wind_capacity_factor`: Stützpunkte inkl. Caps und Höhenkorrektur.
- `analyze_location` (monkeypatched, kein Netz): `effective_renewable_mw <= renewable_mw`
  und `load_coverage` basiert auf `effective_renewable_mw`.

## Doku (#3-Teil)
- `CLAUDE.md`: Load-Coverage-Beschreibung um „erwartete Erzeugung (CF-gewichtet)" ergänzen.
- Memory: Scoring-Block entsprechend aktualisieren.

## Nicht in diesem Scope
- #2 Doppelzählung Grid + Load-Coverage (Grid-Score bleibt unangetastet).
- #6 Heatmap-Rate-Limit.
- Zeitliches Matching / Dunkelflaute / Speicher (Sache der Twin-Simulation in `core.py`).

## Verifikation
- `.venv/bin/python -m pytest -q` grün.
- App: Detail-Panel zeigt erwartete Erzeugung < Nennleistung; Coverage-Bar/-Prozent
  sinken entsprechend realistisch; Slider verändern nur den Bedarf.
- Keine Regression an Grid-Score, Fuel-Mix-Chart oder Heatmap.
