export class Rack {
  constructor({ id, maxKw, inletTempC = 24, cpuUtilization = 0.5 }) {
    this.id = id;
    this.maxKw = maxKw;
    this.inletTempC = inletTempC;
    this.cpuUtilization = cpuUtilization;
  }

  update({ inletTempC, cpuUtilization, maxKw }) {
    if (typeof inletTempC === 'number') this.inletTempC = inletTempC;
    if (typeof cpuUtilization === 'number') this.cpuUtilization = cpuUtilization;
    if (typeof maxKw === 'number') this.maxKw = maxKw;
  }

  get demandKw() {
    return Number((this.maxKw * this.cpuUtilization).toFixed(2));
  }

  get health() {
    if (this.inletTempC > 30) return 'critical';
    if (this.inletTempC > 27 || this.cpuUtilization > 0.9) return 'warning';
    return 'good';
  }
}

export class DataHall {
  constructor({ id, pue = 1.25, racks = [] }) {
    this.id = id;
    this.pue = pue;
    this.racks = racks.map((rack) => new Rack(rack));
  }

  update({ pue, racks }) {
    if (typeof pue === 'number') this.pue = pue;
    if (Array.isArray(racks)) {
      for (const incoming of racks) {
        const existing = this.racks.find((r) => r.id === incoming.id);
        if (existing) {
          existing.update(incoming);
        } else {
          this.racks.push(new Rack(incoming));
        }
      }
    }
  }

  get itLoadKw() {
    return Number(this.racks.reduce((sum, rack) => sum + rack.demandKw, 0).toFixed(2));
  }

  get facilityLoadKw() {
    return Number((this.itLoadKw * this.pue).toFixed(2));
  }

  get avgInletTempC() {
    if (!this.racks.length) return 0;
    const sum = this.racks.reduce((acc, rack) => acc + rack.inletTempC, 0);
    return Number((sum / this.racks.length).toFixed(2));
  }
}

export class RenewableAsset {
  constructor({ id, type, capacityKw, outputKw = 0 }) {
    this.id = id;
    this.type = type;
    this.capacityKw = capacityKw;
    this.outputKw = outputKw;
  }

  update({ outputKw, capacityKw }) {
    if (typeof outputKw === 'number') {
      this.outputKw = Math.max(0, Math.min(outputKw, this.capacityKw));
    }
    if (typeof capacityKw === 'number') {
      this.capacityKw = capacityKw;
      this.outputKw = Math.min(this.outputKw, capacityKw);
    }
  }
}

export class Battery {
  constructor({ id, capacityKwh, soc = 0.5, maxChargeKw = 5000, maxDischargeKw = 5000 }) {
    this.id = id;
    this.capacityKwh = capacityKwh;
    this.soc = soc;
    this.maxChargeKw = maxChargeKw;
    this.maxDischargeKw = maxDischargeKw;
  }

  update({ soc }) {
    if (typeof soc === 'number') this.soc = Math.max(0, Math.min(1, soc));
  }

  get availableDischargeKw() {
    return Number((this.maxDischargeKw * this.soc).toFixed(2));
  }
}

export class HyperscalerTwin {
  constructor({ halls = [], renewables = [], batteries = [], weather = {}, grid = {} }) {
    this.halls = halls.map((hall) => new DataHall(hall));
    this.renewables = renewables.map((r) => new RenewableAsset(r));
    this.batteries = batteries.map((b) => new Battery(b));
    this.weather = weather;
    this.grid = grid;
    this.lastUpdate = new Date().toISOString();
  }

  applyTelemetry(payload) {
    if (payload.weather) {
      this.weather = { ...this.weather, ...payload.weather };
    }

    if (payload.grid) {
      this.grid = { ...this.grid, ...payload.grid };
    }

    if (Array.isArray(payload.halls)) {
      for (const hall of payload.halls) {
        const existing = this.halls.find((h) => h.id === hall.id);
        if (existing) existing.update(hall);
        else this.halls.push(new DataHall(hall));
      }
    }

    if (Array.isArray(payload.renewables)) {
      for (const asset of payload.renewables) {
        const existing = this.renewables.find((r) => r.id === asset.id);
        if (existing) existing.update(asset);
        else this.renewables.push(new RenewableAsset(asset));
      }
    }

    if (Array.isArray(payload.batteries)) {
      for (const battery of payload.batteries) {
        const existing = this.batteries.find((b) => b.id === battery.id);
        if (existing) existing.update(battery);
        else this.batteries.push(new Battery(battery));
      }
    }

    this.lastUpdate = new Date().toISOString();
  }

  toJSON() {
    const itLoadKw = Number(this.halls.reduce((sum, hall) => sum + hall.itLoadKw, 0).toFixed(2));
    const facilityLoadKw = Number(this.halls.reduce((sum, hall) => sum + hall.facilityLoadKw, 0).toFixed(2));
    const renewableKw = Number(this.renewables.reduce((sum, asset) => sum + asset.outputKw, 0).toFixed(2));
    const batteryDischargeKw = Number(this.batteries.reduce((sum, b) => sum + b.availableDischargeKw, 0).toFixed(2));
    const renewableCoverage = facilityLoadKw > 0 ? Number((renewableKw / facilityLoadKw).toFixed(3)) : 0;

    return {
      halls: this.halls,
      renewables: this.renewables,
      batteries: this.batteries,
      weather: this.weather,
      grid: this.grid,
      aggregates: {
        itLoadKw,
        facilityLoadKw,
        renewableKw,
        batteryDischargeKw,
        renewableCoverage,
      },
      lastUpdate: this.lastUpdate,
    };
  }
}

export const defaultModel = {
  halls: [
    {
      id: 'hall-a',
      pue: 1.19,
      racks: [
        { id: 'a-r1', maxKw: 28, inletTempC: 24.5, cpuUtilization: 0.72 },
        { id: 'a-r2', maxKw: 30, inletTempC: 25.1, cpuUtilization: 0.64 },
        { id: 'a-r3', maxKw: 27, inletTempC: 23.8, cpuUtilization: 0.81 },
      ],
    },
    {
      id: 'hall-b',
      pue: 1.24,
      racks: [
        { id: 'b-r1', maxKw: 32, inletTempC: 26.2, cpuUtilization: 0.67 },
        { id: 'b-r2', maxKw: 31, inletTempC: 25.6, cpuUtilization: 0.74 },
        { id: 'b-r3', maxKw: 29, inletTempC: 26.8, cpuUtilization: 0.69 },
      ],
    },
    {
      id: 'hall-c',
      pue: 1.22,
      racks: [
        { id: 'c-r1', maxKw: 35, inletTempC: 24.4, cpuUtilization: 0.58 },
        { id: 'c-r2', maxKw: 35, inletTempC: 24.2, cpuUtilization: 0.55 },
        { id: 'c-r3', maxKw: 35, inletTempC: 24.7, cpuUtilization: 0.61 },
      ],
    },
  ],
  renewables: [
    { id: 'solar-west', type: 'solar', capacityKw: 20000, outputKw: 14500 },
    { id: 'solar-east', type: 'solar', capacityKw: 12000, outputKw: 8300 },
    { id: 'wind-1', type: 'wind', capacityKw: 18000, outputKw: 9200 },
  ],
  batteries: [{ id: 'bess-1', capacityKwh: 60000, soc: 0.68, maxChargeKw: 10000, maxDischargeKw: 10000 }],
  weather: { ambientTempC: 29.4, ghiWm2: 801, windSpeedMs: 8.2, condition: 'partly_cloudy' },
  grid: { co2IntensityGPerKwh: 313, priceEurPerMwh: 142 },
};
