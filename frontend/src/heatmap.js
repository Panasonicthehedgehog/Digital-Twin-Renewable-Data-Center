/**
 * HeatmapLayer – Leaflet canvas overlay for the renewable-potential grid.
 *
 * Renders a semi-transparent grid of coloured cells on a full-viewport canvas
 * that sits on top of the map tiles. All mouse events pass through so the
 * normal map click/drag behaviour is preserved.
 *
 * Usage:
 *   import { HeatmapLayer } from './heatmap.js';
 *   const layer = new HeatmapLayer({ opacity: 0.65 });
 *   map.addLayer(layer);
 */

import L from 'leaflet';

// Same origin: Vite proxies /api in dev, FastAPI serves the app in the
// packaged build. Never hardcode localhost here — desktop.py uses a random port.
const API_BASE = '';

function heatColor(score) {
  const h = (score / 100) * 120;
  return `hsl(${h}, 75%, 45%)`;
}

// Scores are rounded to one decimal by the backend; cache the 1001 strings
// instead of rebuilding an HSL string for every cell on every redraw.
const COLOR_CACHE = Array.from({ length: 1001 }, (_, i) => heatColor(i / 10));

export const HeatmapLayer = L.Layer.extend({

  options: {
    opacity: 0.65,
    minZoom: 5,
  },

  initialize(options) {
    L.setOptions(this, options);
    this._grid = null;
    this._fetching = false;
    this._fetchTimer = null;
    this._abortController = null;
    this._requestId = 0;
    this._drawScheduled = false;
  },

  onAdd(map) {
    this._map = map;

    this._canvas = L.DomUtil.create('canvas', 'heatmap-canvas');
    this._canvas.style.cssText = [
      'position: absolute',
      'top: 0',
      'left: 0',
      'pointer-events: none',
      'z-index: 400',
    ].join(';');

    map.getContainer().appendChild(this._canvas);
    this._resize();

    // Redraw on every view change (pan/zoom) — throttled to one frame.
    map.on('move', this._scheduleDraw, this);
    // Fetch new data only after movement settles
    map.on('moveend', this._scheduleFetch, this);
    map.on('resize', this._resize, this);

    this._fetch();
  },

  onRemove(map) {
    map.off('move', this._scheduleDraw, this);
    map.off('moveend', this._scheduleFetch, this);
    map.off('resize', this._resize, this);
    this._abortController?.abort();
    clearTimeout(this._fetchTimer);
    if (this._canvas && this._canvas.parentNode) {
      this._canvas.parentNode.removeChild(this._canvas);
    }
    this._canvas = null;
  },

  _resize() {
    const size = this._map.getSize();
    this._canvas.width = size.x;
    this._canvas.height = size.y;
    this._canvas.style.width = `${size.x}px`;
    this._canvas.style.height = `${size.y}px`;
    this._draw();
  },

  _scheduleDraw() {
    if (this._drawScheduled) return;
    this._drawScheduled = true;
    requestAnimationFrame(() => {
      this._drawScheduled = false;
      this._draw();
    });
  },

  _scheduleFetch() {
    if (this._map.getZoom() < this.options.minZoom) {
      this._abortController?.abort();
      this._grid = null;
      this._draw();
      return;
    }
    clearTimeout(this._fetchTimer);
    this._fetchTimer = setTimeout(() => this._fetch(), 400);
  },

  _fetch() {
    const bounds = this._map.getBounds();
    const n = bounds.getNorth();
    const s = bounds.getSouth();
    const e = bounds.getEast();
    const w = bounds.getWest();

    if (this._map.getZoom() < this.options.minZoom) {
      this._abortController?.abort();
      this._grid = null;
      this._draw();
      return;
    }

    this._fetching = true;

    // Cancel the previous request so a slow, stale response cannot overwrite
    // a newer grid.
    this._abortController?.abort();
    const controller = new AbortController();
    this._abortController = controller;
    const requestId = ++this._requestId;

    fetch(`${API_BASE}/api/heatmap/grid`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ north: n, south: s, east: e, west: w }),
      signal: controller.signal,
    })
      .then(r => r.json())
      .then(data => {
        if (requestId !== this._requestId) return;
        this._grid = data;
        this._draw();
      })
      .catch(err => {
        if (err.name === 'AbortError' || requestId !== this._requestId) return;
        this._grid = null;
        this._draw();
      })
      .finally(() => {
        if (requestId === this._requestId) this._fetching = false;
      });
  },

  _draw() {
    if (!this._map || !this._canvas) return;

    const ctx = this._canvas.getContext('2d');
    const size = this._map.getSize();
    ctx.clearRect(0, 0, size.x, size.y);

    if (this._map.getZoom() < this.options.minZoom) return;

    const g = this._grid;
    if (!g || !g.potential) return;

    const grid = g.potential;
    const { north, south, east, west } = g.bounds;
    const res = g.resolution;

    const v = this._map.getBounds();
    const vn = Math.min(v.getNorth(), north);
    const vs = Math.max(v.getSouth(), south);
    const ve = Math.min(v.getEast(), east);
    const vw = Math.max(v.getWest(), west);

    const row0 = Math.max(0, Math.floor((north - vn) / res));
    const row1 = Math.min(g.rows - 1, Math.ceil((north - vs) / res));
    const col0 = Math.max(0, Math.floor((vw - west) / res));
    const col1 = Math.min(g.cols - 1, Math.ceil((ve - west) / res));

    // In Web Mercator, x depends only on longitude and y only on latitude.
    // Project each grid line once instead of projecting two corners per cell.
    const colX = [];
    for (let cj = col0; cj <= col1 + 1; cj++) {
      colX.push(this._map.latLngToContainerPoint([north, west + cj * res]).x);
    }
    const rowY = [];
    for (let ri = row0; ri <= row1 + 1; ri++) {
      rowY.push(this._map.latLngToContainerPoint([north - ri * res, west]).y);
    }

    ctx.globalAlpha = this.options.opacity;

    for (let ri = row0; ri <= row1; ri++) {
      const y0 = Math.min(rowY[ri - row0], rowY[ri - row0 + 1]);
      const h = Math.max(1, Math.abs(rowY[ri - row0 + 1] - rowY[ri - row0]));
      for (let cj = col0; cj <= col1; cj++) {
        const score = grid[ri][cj];
        if (score == null) continue;

        const x0 = Math.min(colX[cj - col0], colX[cj - col0 + 1]);
        const w = Math.max(1, Math.abs(colX[cj - col0 + 1] - colX[cj - col0]));

        const colorIndex = Math.max(0, Math.min(1000, Math.round(score * 10)));
        ctx.fillStyle = COLOR_CACHE[colorIndex];
        ctx.fillRect(x0, y0, w, h);
      }
    }
  },

});
