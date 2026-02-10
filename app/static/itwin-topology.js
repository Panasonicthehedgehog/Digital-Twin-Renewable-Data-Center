import { Point3d } from 'https://esm.sh/@itwin/core-geometry@4.9.6';

const canvas = document.getElementById('itwin-topology');
const ctx = canvas?.getContext('2d');

function isoProject(point) {
  const x = (point.x - point.y) * 0.866;
  const y = (point.x + point.y) * 0.5 - point.z;
  return { x, y };
}

function drawBlock(origin, width, depth, height, color) {
  const p0 = isoProject(Point3d.create(origin.x, origin.y, origin.z));
  const p1 = isoProject(Point3d.create(origin.x + width, origin.y, origin.z));
  const p2 = isoProject(Point3d.create(origin.x + width, origin.y + depth, origin.z));
  const p3 = isoProject(Point3d.create(origin.x, origin.y + depth, origin.z));
  const p4 = isoProject(Point3d.create(origin.x, origin.y, origin.z + height));
  const p5 = isoProject(Point3d.create(origin.x + width, origin.y, origin.z + height));
  const p6 = isoProject(Point3d.create(origin.x + width, origin.y + depth, origin.z + height));
  const p7 = isoProject(Point3d.create(origin.x, origin.y + depth, origin.z + height));

  ctx.fillStyle = `${color}99`;
  ctx.strokeStyle = color;
  ctx.lineWidth = 1.3;

  // top
  ctx.beginPath();
  ctx.moveTo(p4.x, p4.y);
  ctx.lineTo(p5.x, p5.y);
  ctx.lineTo(p6.x, p6.y);
  ctx.lineTo(p7.x, p7.y);
  ctx.closePath();
  ctx.fill();
  ctx.stroke();

  // side
  ctx.beginPath();
  ctx.moveTo(p5.x, p5.y);
  ctx.lineTo(p6.x, p6.y);
  ctx.lineTo(p2.x, p2.y);
  ctx.lineTo(p1.x, p1.y);
  ctx.closePath();
  ctx.fill();
  ctx.stroke();

  // front
  ctx.beginPath();
  ctx.moveTo(p4.x, p4.y);
  ctx.lineTo(p7.x, p7.y);
  ctx.lineTo(p3.x, p3.y);
  ctx.lineTo(p0.x, p0.y);
  ctx.closePath();
  ctx.fill();
  ctx.stroke();
}

export function renderItwinTopology(state) {
  if (!canvas || !ctx) return;

  ctx.clearRect(0, 0, canvas.width, canvas.height);
  ctx.save();
  ctx.translate(165, 235);

  const halls = state.halls ?? [];
  const palette = ['#42b3ff', '#47dd8a', '#ffc655', '#ff8f7e'];

  halls.forEach((hall, idx) => {
    const width = 60;
    const depth = 40;
    const height = 12 + Math.round((hall.itLoadKw ?? 0) / 6);
    drawBlock({ x: idx * 80, y: idx * 12, z: 0 }, width, depth, height, palette[idx % palette.length]);
    ctx.fillStyle = '#dcecff';
    ctx.font = '12px Inter, system-ui, sans-serif';
    const label = isoProject(Point3d.create(idx * 80 + 5, idx * 12 + 10, height + 4));
    ctx.fillText(`${hall.id} · ${hall.itLoadKw} kW`, label.x, label.y);
  });

  ctx.restore();
}
