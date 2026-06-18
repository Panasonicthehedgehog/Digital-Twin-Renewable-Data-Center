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

const API_BASE = 'http://localhost:8000';

function heatColor(score) {
  const h = (score / 100) * 120;
  return `hsl(${h}, 75%, 45%)`;
}

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

    // Redraw on every view change (pan/zoom) — lightweight, no fetch
    map.on('move', this._draw, this);
    // Fetch new data only after movement settles
    map.on('moveend', this._scheduleFetch, this);
    map.on('resize', this._resize, this);

    this._fetch();
  },

  onRemove(map) {
    map.off('move', this._draw, this);
    map.off('moveend', this._scheduleFetch, this);
    map.off('resize', this._resize, this);
    if (this._canvas && this._canvas.parentNode) {
      this._canvas.parentNode.removeChild(this._canvas);
    }
  },

  _resize() {
    const size = this._map.getSize();
    this._canvas.width = size.x;
    this._canvas.height = size.y;
    this._canvas.style.width = `${size.x}px`;
    this._canvas.style.height = `${size.y}px`;
    this._draw();
  },

  _scheduleFetch() {
    if (this._map.getZoom() < this.options.minZoom) {
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
      this._grid = null;
      this._draw();
      return;
    }

    this._fetching = true;

    fetch(`${API_BASE}/api/heatmap/grid`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ north: n, south: s, east: e, west: w }),
    })
      .then(r => r.json())
      .then(data => {
        this._grid = data;
        this._draw();
      })
      .catch(() => {
        this._grid = null;
        this._draw();
      })
      .finally(() => { this._fetching = false; });
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

    for (let ri = row0; ri <= row1; ri++) {
      for (let cj = col0; cj <= col1; cj++) {
        const score = grid[ri][cj];
        if (score == null) continue;

        const lat0 = north - ri * res;
        const lng0 = west + cj * res;
        const lat1 = lat0 - res;
        const lng1 = lng0 + res;

        const p0 = this._map.latLngToContainerPoint([lat0, lng0]);
        const p1 = this._map.latLngToContainerPoint([lat1, lng1]);

        const x = Math.min(p0.x, p1.x);
        const y = Math.min(p0.y, p1.y);
        const w = Math.max(1, Math.abs(p1.x - p0.x));
        const h = Math.max(1, Math.abs(p1.y - p0.y));

        ctx.fillStyle = heatColor(score);
        ctx.globalAlpha = this.options.opacity;
        ctx.fillRect(x, y, w, h);
      }
    }
  },

});
