import { HyperscalerTwin, defaultModel } from './twin.js';
import { renderItwinTopology } from './itwin-topology.js';

const localTwin = new HyperscalerTwin(defaultModel);
const stateEls = {
  itLoad: document.getElementById('it-load'),
  facilityLoad: document.getElementById('facility-load'),
  renewable: document.getElementById('renewable'),
  coverage: document.getElementById('coverage'),
  weather: document.getElementById('weather'),
  grid: document.getElementById('grid'),
  halls: document.getElementById('halls'),
  lastUpdate: document.getElementById('last-update'),
};

function hallCard(hall) {
  const rackRows = hall.racks
    .map((rack) => `<tr><td>${rack.id}</td><td>${rack.demandKw} kW</td><td>${rack.inletTempC} °C</td><td>${rack.health}</td></tr>`)
    .join('');

  return `
    <article class="card hall">
      <h3>${hall.id.toUpperCase()}</h3>
      <p>IT Load: <b>${hall.itLoadKw} kW</b> · Facility: <b>${hall.facilityLoadKw} kW</b> · PUE: <b>${hall.pue}</b></p>
      <table>
        <thead><tr><th>Rack</th><th>Demand</th><th>Inlet</th><th>Status</th></tr></thead>
        <tbody>${rackRows}</tbody>
      </table>
    </article>
  `;
}

function render(state) {
  stateEls.itLoad.textContent = `${state.aggregates.itLoadKw.toLocaleString()} kW`;
  stateEls.facilityLoad.textContent = `${state.aggregates.facilityLoadKw.toLocaleString()} kW`;
  stateEls.renewable.textContent = `${state.aggregates.renewableKw.toLocaleString()} kW`;
  stateEls.coverage.textContent = `${Math.round(state.aggregates.renewableCoverage * 100)} %`;
  stateEls.weather.textContent = `${state.weather.ambientTempC} °C · GHI ${state.weather.ghiWm2} W/m² · Wind ${state.weather.windSpeedMs} m/s`;
  stateEls.grid.textContent = `${state.grid.co2IntensityGPerKwh} gCO₂/kWh · ${state.grid.priceEurPerMwh} €/MWh`;
  stateEls.halls.innerHTML = state.halls.map(hallCard).join('');
  stateEls.lastUpdate.textContent = new Date(state.lastUpdate).toLocaleString();

  const renewableRatio = Math.min(1, state.aggregates.renewableKw / Math.max(state.aggregates.facilityLoadKw, 1));
  document.getElementById('renewable-fill').style.width = `${Math.round(renewableRatio * 100)}%`;

  renderItwinTopology(state);
}

async function refreshFromApi() {
  try {
    const response = await fetch('/api/v1/state');
    if (!response.ok) throw new Error('state fetch failed');
    const payload = await response.json();
    localTwin.applyTelemetry(payload);
    render(localTwin.toJSON());
  } catch (error) {
    document.getElementById('api-status').textContent = `API offline: ${error.message}. Showing local twin fallback.`;
    render(localTwin.toJSON());
  }
}

render(localTwin.toJSON());
refreshFromApi();
setInterval(refreshFromApi, 5000);
