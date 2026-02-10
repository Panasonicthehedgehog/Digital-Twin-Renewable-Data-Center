import './styles.css';

const stateEl = document.createElement('div');
stateEl.id = 'state';

document.querySelector('#app').innerHTML = `
  <h1>Hyperscale AI Data Center Digital Twin</h1>
  <div class="panel controls">
    <label>Scenario <select id="scenario"></select></label>
    <button id="applyScenario">Apply</button>
    <label>AI Intensity <input id="aiIntensity" type="number" min="0.05" max="1" step="0.01"></label>
    <label>Grid kW <input id="gridKw" type="number" min="1000" step="100"></label>
    <label>Hydrogen kWh <input id="h2kwh" type="number" min="0" step="500"></label>
    <button id="saveConfig">Update Config</button>
  </div>
  <div id="state"></div>
`;

const stateContainer = document.querySelector('#state');
let latestState = null;
let currentConfig = null;

function stressColor(v) {
  const r = Math.round(255 * v);
  const g = Math.round(255 * (1 - v));
  return `rgb(${r},${g},90)`;
}

function render(state) {
  latestState = state;
  const halls = state.hierarchy.flatMap((b) => b.halls);
  const racks = halls.flatMap((h) => h.racks);
  stateContainer.innerHTML = `
    <div class="grid">
      <div class="panel kpi"><div>Facility Load</div><div class="value">${state.loads.facility_kw.toFixed(1)} kW</div></div>
      <div class="panel kpi"><div>Renewables</div><div class="value">${state.energy.renewables_kw.toFixed(1)} kW</div></div>
      <div class="panel kpi"><div>Stress Index</div><div class="value">${(state.system.stress_index * 100).toFixed(1)}%</div></div>
      <div class="panel kpi"><div>Status</div><div class="value">${state.system.failed ? 'FAILED' : 'OPERATING'}</div></div>
    </div>
    <div class="panel">
      <h3>Weather</h3>
      <div>${state.weather.ambient_temp_c} °C | Wind ${state.weather.wind_speed_ms} m/s | Solar ${state.weather.solar_irradiance_wm2} W/m²</div>
      <div>Scenario: ${state.scenario} ${state.system.hydrogen_bridge_active ? ' | Hydrogen bridge active' : ''}</div>
      ${state.system.failed ? `<div style="color:#ff8080">Failure: ${state.system.failure_reason}</div>` : ''}
    </div>
    <div class="panel">
      <h3>Rack Stress Heatmap (Pseudo-3D Topology)</h3>
      <div class="rack-grid">${racks.map((r) => `<div class="rack" title="${r.id} stress ${r.stress}" style="background:${stressColor(r.stress)}"></div>`).join('')}</div>
    </div>
    <div class="panel">
      <h3>Energy Flow</h3>
      <div>Solar ${state.energy.solar_kw} kW | Wind ${state.energy.wind_kw} kW | Battery ${state.energy.battery_kw} kW (SOC ${(state.energy.battery_soc*100).toFixed(1)}%) | Hydrogen ${state.energy.hydrogen_kw} kW (SOC ${(state.energy.hydrogen_soc*100).toFixed(1)}%) | Grid ${state.energy.grid_kw} kW / ${state.energy.grid_capacity_kw} kW</div>
      <div>Unserved load: ${state.energy.unmet_kw} kW</div>
    </div>
  `;
}

async function loadScenarios() {
  const res = await fetch('http://localhost:8000/api/scenarios');
  const data = await res.json();
  const sel = document.getElementById('scenario');
  sel.innerHTML = data.scenarios.map((s) => `<option value="${s}">${s}</option>`).join('');
}

async function loadConfig() {
  const res = await fetch('http://localhost:8000/api/config');
  currentConfig = await res.json();
  document.getElementById('aiIntensity').value = currentConfig.load.ai_intensity;
  document.getElementById('gridKw').value = currentConfig.energy.grid_capacity_kw;
  document.getElementById('h2kwh').value = currentConfig.energy.hydrogen_capacity_kwh;
}

document.getElementById('applyScenario').onclick = async () => {
  const name = document.getElementById('scenario').value;
  const res = await fetch('http://localhost:8000/api/scenario', { method: 'POST', headers: {'Content-Type':'application/json'}, body: JSON.stringify({ name }) });
  const data = await res.json();
  render(data.state);
};

document.getElementById('saveConfig').onclick = async () => {
  currentConfig.load.ai_intensity = Number(document.getElementById('aiIntensity').value);
  currentConfig.energy.grid_capacity_kw = Number(document.getElementById('gridKw').value);
  currentConfig.energy.hydrogen_capacity_kwh = Number(document.getElementById('h2kwh').value);
  const res = await fetch('http://localhost:8000/api/config', { method: 'PUT', headers: {'Content-Type':'application/json'}, body: JSON.stringify(currentConfig) });
  const data = await res.json();
  render(data.state);
};

const ws = new WebSocket('ws://localhost:8000/ws/state');
ws.onmessage = (event) => render(JSON.parse(event.data));

await loadScenarios();
await loadConfig();
