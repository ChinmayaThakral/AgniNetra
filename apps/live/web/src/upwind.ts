import type { Cell, Wind } from "./schema";

// "What's that smoke?": trace air back from a point for six hours using the feed's wind
// grid, and list the fire cells near that path. It runs on the phone, so the user's
// location never leaves the device.
//
// The corridor half width is a first setting, not a tuned one: 25 km, about two cells
// either side of the path, chosen before any result was looked at.

export const CORRIDOR_KM = 25;
const KM_PER_DEG = 111.32;

export type Point = [number, number];

export interface Source {
  cell: Cell;
  hoursAgo: number;
  distanceKm: number;
}

function nearestIndex(wind: Wind, [lon, lat]: Point): number {
  let best = 0;
  let bestDistance = Infinity;
  wind.points.forEach(([plon, plat], i) => {
    const d = (plon - lon) ** 2 + (plat - lat) ** 2;
    if (d < bestDistance) {
      best = i;
      bestDistance = d;
    }
  });
  return best;
}

// Step one hour upwind. Wind direction is the bearing it blows from, so the air arriving
// here came from that bearing, at the wind's speed.
export function stepUpwind([lon, lat]: Point, speedKmh: number, fromDeg: number): Point {
  const bearing = (fromDeg * Math.PI) / 180;
  const dLat = (speedKmh * Math.cos(bearing)) / KM_PER_DEG;
  const dLon = (speedKmh * Math.sin(bearing)) / (KM_PER_DEG * Math.cos((lat * Math.PI) / 180));
  return [lon + dLon, lat + dLat];
}

export function backTrajectory(origin: Point, wind: Wind): Point[] {
  const path: Point[] = [origin];
  const hours = wind.hours_ist.length;
  let here = origin;
  for (let h = hours - 1; h >= 1; h -= 1) {
    const point = wind.points[nearestIndex(wind, here)];
    const sample = point?.[2][h];
    if (!sample || sample[0] === null || sample[1] === null) break;
    here = stepUpwind(here, sample[0], sample[1]);
    path.push(here);
  }
  return path;
}

function kmBetween([lon1, lat1]: Point, [lon2, lat2]: Point): number {
  const meanLat = (((lat1 + lat2) / 2) * Math.PI) / 180;
  const dx = (lon2 - lon1) * KM_PER_DEG * Math.cos(meanLat);
  const dy = (lat2 - lat1) * KM_PER_DEG;
  return Math.hypot(dx, dy);
}

// Distance from a point to a segment, and how far along it the closest point sits.
function toSegment(p: Point, a: Point, b: Point): { km: number; t: number } {
  const meanLat = (a[1] * Math.PI) / 180;
  const ax = 0;
  const ay = 0;
  const bx = (b[0] - a[0]) * Math.cos(meanLat);
  const by = b[1] - a[1];
  const px = (p[0] - a[0]) * Math.cos(meanLat);
  const py = p[1] - a[1];
  const length = bx * bx + by * by;
  const t = length === 0 ? 0 : Math.max(0, Math.min(1, ((px - ax) * bx + (py - ay) * by) / length));
  const cx = bx * t;
  const cy = by * t;
  return { km: Math.hypot(px - cx, py - cy) * KM_PER_DEG, t };
}

export function upwindSources(origin: Point, wind: Wind, cells: Cell[]): { path: Point[]; sources: Source[] } {
  const path = backTrajectory(origin, wind);
  const sources: Source[] = [];
  for (const cell of cells) {
    let best: { km: number; hours: number } | null = null;
    for (let i = 0; i + 1 < path.length; i += 1) {
      const a = path[i];
      const b = path[i + 1];
      if (!a || !b) continue;
      const { km, t } = toSegment(cell.centre, a, b);
      if (km <= CORRIDOR_KM && (best === null || km < best.km)) best = { km, hours: i + t };
    }
    if (best) {
      sources.push({ cell, hoursAgo: Math.round(best.hours * 10) / 10, distanceKm: Math.round(kmBetween(origin, cell.centre)) });
    }
  }
  sources.sort((x, y) => x.hoursAgo - y.hoursAgo || x.distanceKm - y.distanceKm);
  return { path, sources };
}
