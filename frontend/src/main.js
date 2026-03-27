/**
 * DC Location Intelligence – Main Application
 * Leaflet map + Chart.js + FastAPI backend
 */

import L from 'leaflet';
import 'leaflet/dist/leaflet.css';
import {
  Chart,
  LinearScale, CategoryScale,
  DoughnutController, ArcElement,
  BarController, BarElement,
  Tooltip, Legend,
} from 'chart.js';
import './styles.css';

// Fix Leaflet default icons in Vite
import markerIcon2x from 'leaflet/dist/images/marker-icon-2x.png';
import markerIcon   from 'leaflet/dist/images/marker-icon.png';
import markerShadow from 'leaflet/dist/images/marker-shadow.png';
delete L.Icon.Default.prototype._getIconUrl;
L.Icon.Default.mergeOptions({ iconRetinaUrl: markerIcon2x, iconUrl: markerIcon, shadowUrl: markerShadow });

Chart.register(
  LinearScale, CategoryScale,
  DoughnutController, ArcElement,
  BarController, BarElement,
  Tooltip, Legend,
);

// ─────────────────────────────────────────────────────────────────────────────
// Configuration
// ─────────────────────────────────────────────────────────────────────────────
const API_BASE = 'http://localhost:8000';
const CIRCUMFERENCE = 2 * Math.PI * 50; // SVG gauge circle r=50

// ─────────────────────────────────────────────────────────────────────────────
// Application State
// ─────────────────────────────────────────────────────────────────────────────
const state = {
  locations: [],      // All analyzed locations
  activeId: null,     // Currently displayed location id
  compared: [],       // Locations added to comparison (max 5)
  markers: new Map(), // leaflet marker per location id
  nextId: 1,
  chartMix: null,
  chartCompare: null,
  chartRegionalMix: null,
};

// ─────────────────────────────────────────────────────────────────────────────
// Helpers
// ─────────────────────────────────────────────────────────────────────────────
function scoreColor(score) {
  if (score >= 80) return '#22c55e';
  if (score >= 65) return '#84cc16';
  if (score >= 50) return '#f59e0b';
  if (score >= 35) return '#f97316';
  return '#ef4444';
}

function scoreLabel(score) {
  if (score >= 80) return 'Excellent';
  if (score >= 65) return 'Good';
  if (score >= 50) return 'Fair';
  if (score >= 35) return 'Poor';
  return 'Unsuitable';
}

function recClass(score) {
  if (score >= 65) return '';
  if (score >= 45) return 'warn';
  return 'bad';
}

// Every 24th timestamp label (once per day)
function dayLabels(timestamps) {
  return timestamps.map((t, i) => i % 24 === 0 ? t.slice(5, 10) : '');
}

// PDF energy model (GPU server power at utilization u, §2.1)
function computeCapacityMw(aiIntensity, servers) {
  const u = aiIntensity / 100;
  const kwPerServer = 0.8 + 5.2 * Math.pow(u, 1.2) + 0.6 * u;
  return Math.round(servers * kwPerServer / 1000);
}

// ─────────────────────────────────────────────────────────────────────────────
// API Service
// ─────────────────────────────────────────────────────────────────────────────
async function checkBackend() {
  try {
    const r = await fetch(`${API_BASE}/health`, { signal: AbortSignal.timeout(4000) });
    return r.ok;
  } catch { return false; }
}

async function analyzeLocation(lat, lng, aiIntensity, servers) {
  const body = {
    lat,
    lng,
    servers,
    ai_intensity: aiIntensity / 100,
  };
  const r = await fetch(`${API_BASE}/api/location/analyze`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  if (!r.ok) {
    const err = await r.json().catch(() => ({ detail: r.statusText }));
    throw new Error(err.detail || 'Analysis failed');
  }
  return r.json();
}

// ─────────────────────────────────────────────────────────────────────────────
// Leaflet Map
// ─────────────────────────────────────────────────────────────────────────────
let map;

function initMap() {
  map = L.map('map', {
    center: [30, 10],
    zoom: 3,
    minZoom: 2,
    zoomControl: false,
    maxBounds: [[-85, -180], [85, 180]],
    maxBoundsViscosity: 1.0,
  });

  // CartoDB Positron – clean, light basemap
  L.tileLayer('https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}{r}.png', {
    attribution: '© <a href="https://openstreetmap.org">OSM</a> © <a href="https://carto.com">CARTO</a>',
    subdomains: 'abcd',
    minZoom: 2,
    maxZoom: 18,
    noWrap: true,
  }).addTo(map);

  L.control.zoom({ position: 'topright' }).addTo(map);

  map.on('click', handleMapClick);
}

function createMarkerIcon(score) {
  const color = scoreColor(score);
  const svg = `
    <svg xmlns="http://www.w3.org/2000/svg" width="32" height="40" viewBox="0 0 32 40">
      <path d="M16 0C7.163 0 0 7.163 0 16c0 10 16 24 16 24s16-14 16-24C32 7.163 24.837 0 16 0z"
            fill="${color}" stroke="white" stroke-width="2"/>
      <circle cx="16" cy="15" r="7" fill="white" opacity="0.9"/>
      <text x="16" y="19" text-anchor="middle" font-size="8" font-weight="800" fill="${color}">${Math.round(score)}</text>
    </svg>`;
  return L.divIcon({
    html: svg,
    className: '',
    iconSize: [32, 40],
    iconAnchor: [16, 40],
    popupAnchor: [0, -42],
  });
}

function addMapMarker(locData) {
  const { lat, lng } = locData.location;
  const score = locData.scores.composite;
  const id = locData._id;

  const marker = L.marker([lat, lng], { icon: createMarkerIcon(score) });

  const popup = L.popup({ closeButton: false, offset: [0, 0], maxWidth: 200 });
  popup.setContent(`
    <div class="map-popup">
      <div class="map-popup-name">${locData.location.display}</div>
      <div class="map-popup-score">
        <span class="map-popup-dot" style="background:${scoreColor(score)}"></span>
        Score ${score}/100 · ${scoreLabel(score)}
      </div>
    </div>
  `);
  marker.bindPopup(popup);
  marker.on('click', () => showDetailPanel(locData));
  marker.addTo(map);

  state.markers.set(id, marker);
  return marker;
}

// ─────────────────────────────────────────────────────────────────────────────
// Map click handler
// ─────────────────────────────────────────────────────────────────────────────
async function handleMapClick(e) {
  const { lat, lng } = e.latlng;
  const aiIntensity = Number(document.getElementById('cfg-ai').value);
  const servers = Number(document.getElementById('cfg-servers').value);

  setLoading(true);

  try {
    const result = await analyzeLocation(lat, lng, aiIntensity, servers);
    result._id = state.nextId++;
    state.locations.push(result);
    addMapMarker(result);
    renderSidebarList();
    showDetailPanel(result);
  } catch (err) {
    console.error('Analysis error:', err);
    alert(`Analysis failed: ${err.message}`);
  } finally {
    setLoading(false);
  }
}

// ─────────────────────────────────────────────────────────────────────────────
// Loading overlay
// ─────────────────────────────────────────────────────────────────────────────
function setLoading(on) {
  document.getElementById('map-loading').classList.toggle('hidden', !on);
  document.getElementById('map-hint').style.opacity = on ? '0' : '1';
}

// ─────────────────────────────────────────────────────────────────────────────
// Detail Panel
// ─────────────────────────────────────────────────────────────────────────────
function showDetailPanel(locData) {
  state.activeId = locData._id;

  const panel = document.getElementById('detail-panel');
  panel.classList.remove('panel-closed');

  const s = locData.scores;
  const w = locData.weather;
  const e = locData.energy;
  const mix = e.energy_mix;
  // Header
  document.getElementById('detail-name').textContent = locData.location.display;
  document.getElementById('detail-coords').textContent =
    `${locData.location.lat.toFixed(4)}°, ${locData.location.lng.toFixed(4)}°`;

  // Gauge
  const arc = document.getElementById('gauge-arc');
  const offset = CIRCUMFERENCE * (1 - s.composite / 100);
  arc.style.strokeDashoffset = offset;
  arc.style.stroke = scoreColor(s.composite);
  document.getElementById('gauge-score').textContent = s.composite;

  // Badge
  const badge = document.getElementById('score-badge');
  badge.innerHTML = `
    <span class="badge-value" style="color:${scoreColor(s.composite)}">${scoreLabel(s.composite)}</span>
    <span class="badge-label">Composite: ${s.composite}/100</span>
    <span class="badge-country">${locData.location.city}, ${locData.location.country}</span>
  `;

  // Score bars
  setBar('climate', s.climate);
  setBar('grid', s.grid);
  setBar('load-coverage', s.load_coverage);

  // KPIs
  document.getElementById('kpi-temp').textContent  = w.avg_temperature_c;
  document.getElementById('kpi-wind').textContent  = w.avg_wind_speed_ms;
  document.getElementById('kpi-solar').textContent = Math.round(w.avg_irradiance_wm2);
  document.getElementById('kpi-pue').textContent   = e.estimated_pue;

  // Recommendation
  const rec = document.getElementById('recommendation');
  rec.textContent = locData.recommendation;
  rec.className = `recommendation ${recClass(s.composite)}`;

  // Charts
  if (locData.regional_grid) {
    renderMixChart(mix, e, locData.regional_grid);
    renderRegionalMixChart(locData.regional_grid);
  }


  // Highlight sidebar
  renderSidebarList();

  // Add-to-compare button state
  const alreadyIn = state.compared.some(c => c._id === locData._id);
  const btn = document.getElementById('btn-add-compare');
  btn.disabled = alreadyIn || state.compared.length >= 5;
  btn.innerHTML = alreadyIn
    ? '✓ Already in Comparison'
    : '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 5v14M5 12h14"/></svg> Add to Comparison';
  btn._currentData = locData;
}

function setBar(name, value) {
  const fill = document.getElementById(`bar-${name}`);
  const val  = document.getElementById(`val-${name}`);
  if (fill) { fill.style.width = `${value}%`; fill.style.background = scoreColor(value); }
  if (val)  val.textContent = value;
}

function closeDetailPanel() {
  document.getElementById('detail-panel').classList.add('panel-closed');
  state.activeId = null;
  renderSidebarList();
}

// ─────────────────────────────────────────────────────────────────────────────
// Charts
// ─────────────────────────────────────────────────────────────────────────────

function renderMixChart(_mix, _energy, rg) {
  // Uses real regional plant data (CSV) instead of simulated 3-bucket split
  const ctx = document.getElementById('chart-mix').getContext('2d');
  if (state.chartMix) state.chartMix.destroy();

  const labels = Object.keys(rg.fuel_mix_mw);
  const values = Object.values(rg.fuel_mix_mw);
  const colors = labels.map(l => FUEL_COLORS[l] || '#cbd5e1');
  const total  = values.reduce((a, b) => a + b, 0);

  state.chartMix = new Chart(ctx, {
    type: 'doughnut',
    data: { labels, datasets: [{ data: values, backgroundColor: colors, borderWidth: 2, borderColor: '#fff' }] },
    options: {
      responsive: true, maintainAspectRatio: false, cutout: '65%',
      animation: { duration: 600 },
      plugins: { legend: { display: false }, tooltip: {
        callbacks: { label: c => `${c.label}: ${Math.round(c.parsed).toLocaleString()} MW (${total > 0 ? (c.parsed / total * 100).toFixed(1) : 0} %)` },
      }},
    },
  });

  const legend = document.getElementById('mix-legend');
  legend.innerHTML = labels.map((l, i) => `
    <div class="mix-row">
      <span class="mix-dot" style="background:${colors[i]}"></span>
      <span class="mix-label">${l}</span>
      <span class="mix-pct">${total > 0 ? (values[i] / total * 100).toFixed(1) : 0} %</span>
    </div>
  `).join('');
}

const FUEL_COLORS = {
  'Solar':           '#f59e0b',
  'Wind':            '#0ea5e9',
  'Hydro':           '#3b82f6',
  'Biomass':         '#22c55e',
  'Geothermal':      '#10b981',
  'Other Renewable': '#84cc16',
  'Non-Renewable':   '#94a3b8',
};

// Sort + filter state for the nearby-plants table
const _plantSort  = { col: 'distance_km', dir: 'asc' };
const _plantState = { filter: 'renewable' }; // 'renewable' | 'all'

function renderRegionalMixChart(rg) {
  // Coverage bar
  const capPct = Math.min(100, rg.coverage_ratio_pct);
  document.getElementById('regional-ren-fill').style.width = `${capPct}%`;
  document.getElementById('regional-coverage-pct').textContent = `${rg.coverage_ratio_pct.toFixed(1)} %`;
  document.getElementById('regional-ren-label').textContent =
    `${Math.round(rg.renewable_mw).toLocaleString()} MW renewable`;
  document.getElementById('regional-it-label').textContent =
    `${Math.round(rg.it_load_mw).toLocaleString()} MW needed`;
  document.getElementById('regional-radius').textContent = `${rg.radius_km} km radius`;

  const badge = document.getElementById('regional-coverage-badge');
  if (rg.coverage_possible) {
    badge.textContent = '✓ Regionale Erneuerbaren decken IT Load';
    badge.style.color = '#16a34a';
  } else {
    badge.textContent = '✗ Netznachspeisung erforderlich';
    badge.style.color = '#dc2626';
  }

  // Nearby plants list
  const container = document.getElementById('regional-plant-list');
  if (!container || !rg.top_plants?.length) return;

  // Keep a reference to the plants on the container for re-sorting
  container._plants = rg.top_plants;
  renderPlantTable(container);
}

function renderPlantTable(container) {
  const allPlants = container._plants ?? [];
  const { col, dir } = _plantSort;

  // Apply renewable filter
  const plants = _plantState.filter === 'renewable'
    ? allPlants.filter(p => p.is_renewable)
    : allPlants;

  const sorted = [...plants].sort((a, b) => {
    let av = a[col], bv = b[col];
    if (typeof av === 'string') av = av.toLowerCase();
    if (typeof bv === 'string') bv = bv.toLowerCase();
    if (av < bv) return dir === 'asc' ? -1 : 1;
    if (av > bv) return dir === 'asc' ? 1 : -1;
    return 0;
  });

  const cols = [
    { key: 'name',        label: 'Name' },
    { key: 'fuel',        label: 'Quelle' },
    { key: 'capacity_mw', label: 'MW' },
    { key: 'distance_km', label: 'km' },
  ];

  const arrow = (key) => key !== col ? '' : dir === 'asc' ? ' ↑' : ' ↓';

  const headerCells = cols.map(c =>
    `<span class="plant-th plant-th-${c.key}" data-col="${c.key}">${c.label}${arrow(c.key)}</span>`
  ).join('');

  const rows = sorted.length ? sorted.map(p => {
    const color = FUEL_COLORS[p.fuel] || (p.is_renewable ? '#84cc16' : '#94a3b8');
    return `<div class="plant-row">
      <span class="mix-dot" style="background:${color};flex-shrink:0"></span>
      <span class="plant-name" title="${p.name}">${p.name}</span>
      <span class="plant-fuel" style="color:${color}">${p.fuel}</span>
      <span class="plant-cap">${Math.round(p.capacity_mw).toLocaleString()} MW</span>
      <span class="plant-dist">${p.distance_km} km</span>
    </div>`;
  }).join('') : '<p style="font-size:11px;color:#94a3b8;padding:8px 0">Keine Anlagen gefunden.</p>';

  const isRen = _plantState.filter === 'renewable';
  container.innerHTML = `
    <div class="plant-filter-row">
      <span class="plant-filter-label">Kraftwerke</span>
      <button class="plant-filter-btn ${isRen ? 'active' : ''}" data-filter="renewable">Nur Erneuerbar</button>
      <button class="plant-filter-btn ${!isRen ? 'active' : ''}" data-filter="all">Alle</button>
    </div>
    <div class="plant-header-row">${headerCells}</div>
    ${rows}
  `;

  // Filter toggle
  container.querySelectorAll('.plant-filter-btn').forEach(btn => {
    btn.addEventListener('click', () => {
      _plantState.filter = btn.dataset.filter;
      renderPlantTable(container);
    });
  });

  // Sort on header click
  container.querySelectorAll('.plant-th').forEach(th => {
    th.addEventListener('click', () => {
      const newCol = th.dataset.col;
      if (_plantSort.col === newCol) {
        _plantSort.dir = _plantSort.dir === 'asc' ? 'desc' : 'asc';
      } else {
        _plantSort.col = newCol;
        _plantSort.dir = 'asc';
      }
      renderPlantTable(container);
    });
  });
}

function renderCompareChart() {
  const section = document.getElementById('compare-chart-section');
  if (state.compared.length < 2) {
    section.classList.add('hidden');
    return;
  }
  section.classList.remove('hidden');

  const ctx = document.getElementById('chart-compare').getContext('2d');
  if (state.chartCompare) state.chartCompare.destroy();

  const names       = state.compared.map(l => l.location.city || l.location.display);
  const climate     = state.compared.map(l => l.scores.climate);
  const grid        = state.compared.map(l => l.scores.grid);
  const loadCover   = state.compared.map(l => l.scores.load_coverage ?? 0);

  state.chartCompare = new Chart(ctx, {
    type: 'bar',
    data: {
      labels: names,
      datasets: [
        { label: 'Climate',       data: climate,   backgroundColor: '#10b981' },
        { label: 'Grid',          data: grid,      backgroundColor: '#8b5cf6' },
        { label: 'Load Coverage', data: loadCover, backgroundColor: '#22c55e' },
      ],
    },
    options: {
      responsive: true, maintainAspectRatio: false,
      plugins: { legend: { position: 'top', labels: { font: { size: 12 } } } },
      scales: {
        y: { min: 0, max: 100, title: { display: true, text: 'Score (0–100)' },
             ticks: { stepSize: 20 } },
        x: { ticks: { font: { size: 12 } } },
      },
    },
  });
}

// ─────────────────────────────────────────────────────────────────────────────
// Sidebar Location List
// ─────────────────────────────────────────────────────────────────────────────
function renderSidebarList() {
  const container = document.getElementById('location-list');

  if (state.locations.length === 0) {
    container.innerHTML = `
      <div class="empty-hint">
        <svg width="32" height="32" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5"><path d="M21 10c0 7-9 13-9 13s-9-6-9-13a9 9 0 0118 0z"/><circle cx="12" cy="10" r="3"/></svg>
        <p>Click anywhere on the map to analyse a location</p>
      </div>`;
    return;
  }

  container.innerHTML = state.locations.map(loc => {
    const score = loc.scores.composite;
    const isActive = loc._id === state.activeId;
    return `
      <div class="loc-item ${isActive ? 'active-loc' : ''}" data-id="${loc._id}">
        <span class="loc-dot" style="background:${scoreColor(score)}"></span>
        <div class="loc-info">
          <div class="loc-name">${loc.location.display}</div>
          <div class="loc-score">${scoreLabel(score)} · ${score}/100</div>
        </div>
        <button class="loc-remove" data-remove="${loc._id}" title="Remove">×</button>
      </div>`;
  }).join('');

  // Click on location item → show detail
  container.querySelectorAll('.loc-item').forEach(el => {
    el.addEventListener('click', (e) => {
      if (e.target.closest('[data-remove]')) return;
      const id = Number(el.dataset.id);
      const loc = state.locations.find(l => l._id === id);
      if (loc) {
        map.flyTo([loc.location.lat, loc.location.lng], 7, { duration: 1 });
        showDetailPanel(loc);
      }
    });
  });

  // Remove button
  container.querySelectorAll('[data-remove]').forEach(btn => {
    btn.addEventListener('click', (e) => {
      e.stopPropagation();
      removeLocation(Number(btn.dataset.remove));
    });
  });
}

function removeLocation(id) {
  const marker = state.markers.get(id);
  if (marker) { marker.remove(); state.markers.delete(id); }

  state.locations = state.locations.filter(l => l._id !== id);
  state.compared  = state.compared.filter(l => l._id !== id);

  if (state.activeId === id) closeDetailPanel();

  renderSidebarList();
  renderCompareView();
  updateCompareBadge();
}

// ─────────────────────────────────────────────────────────────────────────────
// Compare View
// ─────────────────────────────────────────────────────────────────────────────
function renderCompareView() {
  const content = document.getElementById('compare-content');
  updateCompareBadge();

  if (state.compared.length === 0) {
    content.innerHTML = `
      <div class="empty-hint large">
        <svg width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1"><rect x="3" y="3" width="7" height="7"/><rect x="14" y="3" width="7" height="7"/><rect x="14" y="14" width="7" height="7"/><rect x="3" y="14" width="7" height="7"/></svg>
        <p>Analyse locations on the map and click "Add to Comparison"</p>
      </div>`;
    document.getElementById('compare-chart-section').classList.add('hidden');
    return;
  }

  const rows = state.compared.map(loc => {
    const s = loc.scores;
    const w = loc.weather;
    const e = loc.energy;
    const bg = scoreColor(s.composite) + '22';
    const fg = scoreColor(s.composite);
    return `
      <tr>
        <td>
          <div class="table-loc-name">${loc.location.display}</div>
          <div class="table-loc-sub">${loc.location.lat.toFixed(2)}°, ${loc.location.lng.toFixed(2)}°</div>
        </td>
        <td><span class="table-score" style="background:${bg};color:${fg}">${s.composite}</span></td>
        <td>${scoreMini(s.climate)}</td>
        <td>${scoreMini(s.grid)}</td>
        <td>${scoreMini(s.load_coverage ?? 0)}</td>
        <td>${w.avg_temperature_c} °C</td>
        <td>${w.avg_wind_speed_ms} m/s</td>
        <td>${Math.round(w.avg_irradiance_wm2)} W/m²</td>
        <td>${e.estimated_pue}</td>
        <td><button class="btn-remove-compare" data-remove="${loc._id}">×</button></td>
      </tr>`;
  }).join('');

  content.innerHTML = `
    <div class="compare-table-wrap">
      <table class="compare-table">
        <thead>
          <tr>
            <th>Location</th>
            <th>Composite</th>
            <th>🌡 Climate</th>
            <th>⚡ Grid</th>
            <th>🔋 Load Cover</th>
            <th>Avg Temp</th>
            <th>Wind Speed</th>
            <th>Irradiance</th>
            <th>PUE</th>
            <th></th>
          </tr>
        </thead>
        <tbody>${rows}</tbody>
      </table>
    </div>`;

  content.querySelectorAll('[data-remove]').forEach(btn => {
    btn.addEventListener('click', () => {
      state.compared = state.compared.filter(l => l._id !== Number(btn.dataset.remove));
      renderCompareView();
      // refresh add-button if panel is open
      if (state.activeId !== null) {
        const loc = state.locations.find(l => l._id === state.activeId);
        if (loc) showDetailPanel(loc);
      }
    });
  });

  renderCompareChart();
}

function scoreMini(value) {
  const color = scoreColor(value);
  return `<span style="color:${color};font-weight:700">${value}</span>`;
}

function updateCompareBadge() {
  const badge = document.getElementById('compare-badge');
  const n = state.compared.length;
  badge.textContent = n;
  badge.classList.toggle('hidden', n === 0);
}

// ─────────────────────────────────────────────────────────────────────────────
// View switching
// ─────────────────────────────────────────────────────────────────────────────
function switchView(viewName) {
  document.querySelectorAll('.view').forEach(v => v.classList.remove('active'));
  document.querySelectorAll('.nav-btn').forEach(b => b.classList.remove('active'));

  document.getElementById(`view-${viewName}`).classList.add('active');
  document.querySelector(`[data-view="${viewName}"]`).classList.add('active');

  if (viewName === 'compare') renderCompareView();
  if (viewName === 'map') {
    setTimeout(() => map.invalidateSize(), 100);
  }
}

// ─────────────────────────────────────────────────────────────────────────────
// UI Bindings
// ─────────────────────────────────────────────────────────────────────────────
function bindUI() {
  // Nav buttons
  document.querySelectorAll('.nav-btn').forEach(btn => {
    btn.addEventListener('click', () => switchView(btn.dataset.view));
  });

  // Close panel
  document.getElementById('btn-close-panel').addEventListener('click', closeDetailPanel);

  // Sliders
  const aiSlider      = document.getElementById('cfg-ai');
  const serversSlider = document.getElementById('cfg-servers');

  function updateCapacityDisplay() {
    const mw = computeCapacityMw(Number(aiSlider.value), Number(serversSlider.value));
    document.getElementById('cfg-capacity-val').textContent = `${mw.toLocaleString()} MW`;
  }

  // Debounced re-analysis of the currently open location
  let _reanalyzeTimer = null;
  async function reanalyzeActive() {
    if (state.activeId === null) return;
    const loc = state.locations.find(l => l._id === state.activeId);
    if (!loc) return;

    setLoading(true);
    try {
      const result = await analyzeLocation(
        loc.location.lat, loc.location.lng,
        Number(aiSlider.value), Number(serversSlider.value),
      );
      result._id = loc._id;

      // Replace in locations list
      const idx = state.locations.findIndex(l => l._id === loc._id);
      if (idx !== -1) state.locations[idx] = result;

      // Update marker icon if score changed
      const marker = state.markers.get(loc._id);
      if (marker) marker.setIcon(createMarkerIcon(result.scores.composite));

      // Sync comparison entry if present
      const cIdx = state.compared.findIndex(c => c._id === loc._id);
      if (cIdx !== -1) state.compared[cIdx] = result;

      showDetailPanel(result);
      renderSidebarList();
    } catch (err) {
      console.error('Re-analysis failed:', err);
    } finally {
      setLoading(false);
    }
  }

  function scheduleReanalyze() {
    clearTimeout(_reanalyzeTimer);
    _reanalyzeTimer = setTimeout(reanalyzeActive, 600);
  }

  aiSlider.addEventListener('input', () => {
    document.getElementById('cfg-ai-val').textContent = `${aiSlider.value} %`;
    updateCapacityDisplay();
    scheduleReanalyze();
  });
  serversSlider.addEventListener('input', () => {
    document.getElementById('cfg-servers-val').textContent = Number(serversSlider.value).toLocaleString();
    updateCapacityDisplay();
    scheduleReanalyze();
  });
  updateCapacityDisplay(); // initial render

  // Add to comparison
  document.getElementById('btn-add-compare').addEventListener('click', () => {
    const btn = document.getElementById('btn-add-compare');
    const loc = btn._currentData;
    if (!loc || state.compared.length >= 5) return;
    if (!state.compared.some(c => c._id === loc._id)) {
      state.compared.push(loc);
      updateCompareBadge();
      btn.disabled = true;
      btn.innerHTML = '✓ Already in Comparison';
    }
  });
}

// ─────────────────────────────────────────────────────────────────────────────
// Status check
// ─────────────────────────────────────────────────────────────────────────────
async function updateStatus() {
  const dot  = document.getElementById('status-dot');
  const text = document.getElementById('status-text');
  const ok   = await checkBackend();
  dot.className  = `status-dot ${ok ? 'online' : 'error'}`;
  text.textContent = ok ? 'Backend connected' : 'Backend offline';
}

// ─────────────────────────────────────────────────────────────────────────────
// Bootstrap
// ─────────────────────────────────────────────────────────────────────────────
async function init() {
  initMap();
  bindUI();
  await updateStatus();
  // Re-check status every 30 s
  setInterval(updateStatus, 30_000);
}

init();
