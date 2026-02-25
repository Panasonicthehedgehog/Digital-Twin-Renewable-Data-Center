/**
 * DC Location Intelligence – Main Application
 * Leaflet map + Chart.js + FastAPI backend
 */

import L from 'leaflet';
import 'leaflet/dist/leaflet.css';
import {
  Chart,
  LineController, LineElement, PointElement,
  LinearScale, CategoryScale,
  DoughnutController, ArcElement,
  BarController, BarElement,
  Tooltip, Legend, Filler,
} from 'chart.js';
import './styles.css';

// Fix Leaflet default icons in Vite
import markerIcon2x from 'leaflet/dist/images/marker-icon-2x.png';
import markerIcon   from 'leaflet/dist/images/marker-icon.png';
import markerShadow from 'leaflet/dist/images/marker-shadow.png';
delete L.Icon.Default.prototype._getIconUrl;
L.Icon.Default.mergeOptions({ iconRetinaUrl: markerIcon2x, iconUrl: markerIcon, shadowUrl: markerShadow });

Chart.register(
  LineController, LineElement, PointElement,
  LinearScale, CategoryScale,
  DoughnutController, ArcElement,
  BarController, BarElement,
  Tooltip, Legend, Filler,
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
  chartEnergy: null,
  chartMix: null,
  chartCompare: null,
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

// ─────────────────────────────────────────────────────────────────────────────
// API Service
// ─────────────────────────────────────────────────────────────────────────────
async function checkBackend() {
  try {
    const r = await fetch(`${API_BASE}/health`, { signal: AbortSignal.timeout(4000) });
    return r.ok;
  } catch { return false; }
}

async function analyzeLocation(lat, lng, capacityMw, aiIntensity) {
  const body = {
    lat,
    lng,
    dc_capacity_mw: capacityMw,
    servers: Math.round(capacityMw * 500),
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
    zoomControl: false,
  });

  // CartoDB Positron – clean, light basemap
  L.tileLayer('https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}{r}.png', {
    attribution: '© <a href="https://openstreetmap.org">OSM</a> © <a href="https://carto.com">CARTO</a>',
    subdomains: 'abcd',
    maxZoom: 18,
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
  const capacityMw = Number(document.getElementById('cfg-capacity').value);
  const aiIntensity = Number(document.getElementById('cfg-ai').value);

  setLoading(true);

  try {
    const result = await analyzeLocation(lat, lng, capacityMw, aiIntensity);
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
  const ts = locData.time_series;

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
  setBar('solar', s.solar);
  setBar('wind', s.wind);
  setBar('climate', s.climate);
  setBar('grid', s.grid);

  // KPIs
  document.getElementById('kpi-temp').textContent  = w.avg_temperature_c;
  document.getElementById('kpi-wind').textContent  = w.avg_wind_speed_ms;
  document.getElementById('kpi-solar').textContent = Math.round(w.avg_irradiance_wm2);
  document.getElementById('kpi-pue').textContent   = e.estimated_pue;

  // Renewable bar
  const renPct = e.avg_renewable_pct;
  document.getElementById('ren-pct').textContent = `${renPct.toFixed(1)} %`;
  document.getElementById('ren-fill').style.width = `${renPct}%`;

  // Recommendation
  const rec = document.getElementById('recommendation');
  rec.textContent = locData.recommendation;
  rec.className = `recommendation ${recClass(s.composite)}`;

  // Charts
  renderEnergyChart(ts);
  renderMixChart(mix, e);

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
function renderEnergyChart(ts) {
  const ctx = document.getElementById('chart-energy').getContext('2d');

  const labels = ts.map((p, i) => i % 24 === 0 ? (p.timestamp || '').slice(5, 10) : '');
  const itLoad = ts.map(p => p.it_load_mw);
  const solar  = ts.map(p => p.solar_mw);
  const wind   = ts.map(p => p.wind_mw);
  const grid   = ts.map(p => p.grid_mw);

  if (state.chartEnergy) state.chartEnergy.destroy();

  state.chartEnergy = new Chart(ctx, {
    type: 'line',
    data: {
      labels,
      datasets: [
        {
          label: 'IT Load', data: itLoad,
          borderColor: '#6366f1', borderWidth: 2,
          pointRadius: 0, fill: false, tension: 0.4,
        },
        {
          label: 'Solar', data: solar,
          borderColor: '#f59e0b', backgroundColor: '#f59e0b20',
          borderWidth: 1.5, pointRadius: 0, fill: true, tension: 0.4,
        },
        {
          label: 'Wind', data: wind,
          borderColor: '#0ea5e9', backgroundColor: '#0ea5e920',
          borderWidth: 1.5, pointRadius: 0, fill: true, tension: 0.4,
        },
        {
          label: 'Grid Import', data: grid,
          borderColor: '#ef4444', borderDash: [4, 3],
          borderWidth: 1.5, pointRadius: 0, fill: false, tension: 0.4,
        },
      ],
    },
    options: {
      responsive: true, maintainAspectRatio: false,
      animation: { duration: 500 },
      plugins: {
        legend: { position: 'bottom', labels: { boxWidth: 10, font: { size: 11 } } },
        tooltip: {
          mode: 'index', intersect: false,
          callbacks: { label: ctx => `${ctx.dataset.label}: ${ctx.parsed.y.toFixed(1)} MW` },
        },
      },
      scales: {
        x: {
          ticks: { maxRotation: 0, font: { size: 10 }, color: '#94a3b8',
            callback: (_, i) => labels[i] },
          grid: { color: '#f1f5f9' },
        },
        y: {
          title: { display: true, text: 'MW', font: { size: 10 }, color: '#94a3b8' },
          ticks: { font: { size: 10 }, color: '#94a3b8' },
          grid: { color: '#f1f5f9' },
        },
      },
    },
  });
}

function renderMixChart(mix, energy) {
  const ctx = document.getElementById('chart-mix').getContext('2d');

  if (state.chartMix) state.chartMix.destroy();

  state.chartMix = new Chart(ctx, {
    type: 'doughnut',
    data: {
      labels: ['Solar', 'Wind', 'Grid'],
      datasets: [{
        data: [mix.solar_pct, mix.wind_pct, mix.grid_pct],
        backgroundColor: ['#f59e0b', '#0ea5e9', '#ef4444'],
        borderWidth: 2, borderColor: '#fff',
      }],
    },
    options: {
      responsive: true, maintainAspectRatio: false,
      cutout: '65%',
      animation: { duration: 600 },
      plugins: { legend: { display: false }, tooltip: {
        callbacks: { label: ctx => `${ctx.label}: ${ctx.parsed.toFixed(1)} %` },
      }},
    },
  });

  // Legend
  const legend = document.getElementById('mix-legend');
  const items = [
    { color: '#f59e0b', label: 'Solar',      pct: mix.solar_pct },
    { color: '#0ea5e9', label: 'Wind',       pct: mix.wind_pct  },
    { color: '#ef4444', label: 'Grid Import', pct: mix.grid_pct  },
  ];
  legend.innerHTML = items.map(it => `
    <div class="mix-row">
      <span class="mix-dot" style="background:${it.color}"></span>
      <span class="mix-label">${it.label}</span>
      <span class="mix-pct">${it.pct.toFixed(1)} %</span>
    </div>
  `).join('');
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

  const names  = state.compared.map(l => l.location.city || l.location.display);
  const solar  = state.compared.map(l => l.scores.solar);
  const wind   = state.compared.map(l => l.scores.wind);
  const climate = state.compared.map(l => l.scores.climate);
  const grid   = state.compared.map(l => l.scores.grid);

  state.chartCompare = new Chart(ctx, {
    type: 'bar',
    data: {
      labels: names,
      datasets: [
        { label: 'Solar',   data: solar,   backgroundColor: '#f59e0b' },
        { label: 'Wind',    data: wind,    backgroundColor: '#0ea5e9' },
        { label: 'Climate', data: climate, backgroundColor: '#10b981' },
        { label: 'Grid',    data: grid,    backgroundColor: '#8b5cf6' },
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
        <td>${scoreMini(s.solar)}</td>
        <td>${scoreMini(s.wind)}</td>
        <td>${scoreMini(s.climate)}</td>
        <td>${scoreMini(s.grid)}</td>
        <td>${w.avg_temperature_c} °C</td>
        <td>${w.avg_wind_speed_ms} m/s</td>
        <td>${Math.round(w.avg_irradiance_wm2)} W/m²</td>
        <td>${e.estimated_pue}</td>
        <td>${e.avg_renewable_pct.toFixed(1)} %</td>
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
            <th>☀ Solar</th>
            <th>💨 Wind</th>
            <th>🌡 Climate</th>
            <th>⚡ Grid</th>
            <th>Avg Temp</th>
            <th>Wind Speed</th>
            <th>Irradiance</th>
            <th>PUE</th>
            <th>Renewable %</th>
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
  const capSlider = document.getElementById('cfg-capacity');
  const aiSlider  = document.getElementById('cfg-ai');
  capSlider.addEventListener('input', () => {
    document.getElementById('cfg-capacity-val').textContent = `${capSlider.value} MW`;
  });
  aiSlider.addEventListener('input', () => {
    document.getElementById('cfg-ai-val').textContent = `${aiSlider.value} %`;
  });

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
