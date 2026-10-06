import type { Boundaries, Cell } from "./schema";
import { type Bounds, fit, type Projection } from "./projection";

// The dark map: district and state outlines, and fire cells drawn as 11 km squares.
// There is no point layer to draw, because the feed carries none.

export const CLASS_COLOURS: Record<Cell["class"], string> = {
  agricultural: "#ffb020",
  industrial: "#ff5a36",
  flare: "#ff2d95",
  unclassified: "#9aa3b2",
};

export const CLASS_LABELS: Record<Cell["class"], string> = {
  agricultural: "likely farm burning",
  industrial: "likely industrial heat",
  flare: "likely gas flare",
  unclassified: "heat, source unclear",
};

const CELL_DEG = 0.1;

function drawOutlines(
  ctx: CanvasRenderingContext2D,
  projection: Projection,
  boundaries: Boundaries,
  kind: "state" | "district",
): void {
  ctx.beginPath();
  for (const feature of boundaries.features) {
    if (feature.properties.kind !== kind) continue;
    const polygons =
      feature.geometry.type === "Polygon" ? [feature.geometry.coordinates] : feature.geometry.coordinates;
    for (const polygon of polygons) {
      for (const ring of polygon) {
        ring.forEach(([lon, lat], i) => {
          const [x, y] = projection.point(lon, lat);
          if (i === 0) ctx.moveTo(x, y);
          else ctx.lineTo(x, y);
        });
      }
    }
  }
  ctx.stroke();
}

export interface MapOptions {
  bounds: Bounds;
  // Show only evening cells.
  untilEvening?: boolean;
  // The Fire Clock: show only cells first seen at or before this IST time, "HH:MM".
  clock?: string;
  // A back trajectory to draw, for "What's that smoke?".
  path?: [number, number][];
}

export function drawFireMap(
  canvas: HTMLCanvasElement,
  boundaries: Boundaries,
  cells: Cell[],
  options: MapOptions,
): void {
  const ratio = window.devicePixelRatio || 1;
  const width = canvas.clientWidth;
  const height = canvas.clientHeight;
  canvas.width = Math.round(width * ratio);
  canvas.height = Math.round(height * ratio);
  const ctx = canvas.getContext("2d");
  if (!ctx) return;
  ctx.setTransform(ratio, 0, 0, ratio, 0, 0);
  // Colours come from the page theme, so the map follows the light and dark switch.
  const css = getComputedStyle(canvas);
  const colour = (name: string, fallback: string): string => css.getPropertyValue(name).trim() || fallback;
  const light = document.documentElement.dataset.theme === "light";
  ctx.fillStyle = colour("--map-ground", "#07090d");
  ctx.fillRect(0, 0, width, height);

  const projection = fit(options.bounds, width, height);
  ctx.lineWidth = 0.4;
  ctx.strokeStyle = colour("--map-district", "rgba(120, 140, 170, 0.18)");
  drawOutlines(ctx, projection, boundaries, "district");
  ctx.lineWidth = 0.9;
  ctx.strokeStyle = colour("--map-state", "rgba(150, 170, 200, 0.45)");
  drawOutlines(ctx, projection, boundaries, "state");

  // Glow adds light on a dark ground and would wash out on a pale one.
  ctx.globalCompositeOperation = light ? "source-over" : "lighter";
  for (const cell of cells) {
    if (options.untilEvening === true && !cell.evening) continue;
    if (options.clock !== undefined && cell.first_seen_ist > options.clock) continue;
    const [lon, lat] = cell.centre;
    const [x0, y0] = projection.point(lon - CELL_DEG / 2, lat + CELL_DEG / 2);
    const [x1, y1] = projection.point(lon + CELL_DEG / 2, lat - CELL_DEG / 2);
    const size = Math.max(2, x1 - x0);
    ctx.shadowColor = CLASS_COLOURS[cell.class];
    ctx.shadowBlur = size * 2;
    ctx.fillStyle = CLASS_COLOURS[cell.class];
    ctx.globalAlpha = cell.how_sure === "medium" ? 0.95 : 0.6;
    ctx.fillRect(x0, y0, size, Math.max(2, y1 - y0));
  }
  ctx.globalAlpha = 1;
  ctx.shadowBlur = 0;
  ctx.globalCompositeOperation = "source-over";

  if (options.path && options.path.length > 1) {
    ctx.strokeStyle = colour("--polar", "#9ec5ff");
    ctx.lineWidth = 2;
    ctx.setLineDash([6, 5]);
    ctx.beginPath();
    options.path.forEach(([lon, lat], i) => {
      const [x, y] = projection.point(lon, lat);
      if (i === 0) ctx.moveTo(x, y);
      else ctx.lineTo(x, y);
    });
    ctx.stroke();
    ctx.setLineDash([]);
    const start = options.path[0];
    if (start) {
      const [x, y] = projection.point(start[0], start[1]);
      ctx.fillStyle = colour("--text", "#ffffff");
      ctx.beginPath();
      ctx.arc(x, y, 5, 0, Math.PI * 2);
      ctx.fill();
    }
  }
}
