import { CLASS_COLOURS } from "./fire-map";
import type { Feed } from "./schema";

// 9:16 images for an Instagram story or WhatsApp status. Every card carries the how sure
// note and "not an official count", and the credits in small type, like every screen.

const W = 1080;
const H = 1920;
const CREDITS = [
  "Data Source MOSDAC/SAC/ISRO. NASA FIRMS. Boundaries (c) OpenStreetMap contributors, ODbL.",
  "Fires shown per 11 km cell, never as individual fields.",
];

function line(ctx: CanvasRenderingContext2D, text: string, y: number, size: number, colour = "#e8edf5"): void {
  ctx.fillStyle = colour;
  ctx.font = `600 ${size}px system-ui, sans-serif`;
  ctx.textAlign = "center";
  ctx.fillText(text, W / 2, y, W - 80);
}

function frame(title: string, subtitle: string, sure: string, body: (ctx: CanvasRenderingContext2D) => void): HTMLCanvasElement {
  const canvas = document.createElement("canvas");
  canvas.width = W;
  canvas.height = H;
  const ctx = canvas.getContext("2d");
  if (!ctx) return canvas;
  ctx.fillStyle = "#07090d";
  ctx.fillRect(0, 0, W, H);
  line(ctx, "AgniNetra", 140, 64, "#ffb020");
  line(ctx, title, 230, 56);
  line(ctx, subtitle, 300, 36, "#9aa3b2");
  body(ctx);
  line(ctx, `how sure: ${sure}`, 1640, 30, "#ffcf70");
  ctx.font = "22px system-ui, sans-serif";
  ctx.fillStyle = "#6f7888";
  CREDITS.forEach((text, i) => ctx.fillText(text, W / 2, 1740 + i * 34, W - 80));
  return canvas;
}

function pct(share: number | null): string {
  return share === null ? "-" : `${Math.round(share * 100)}%`;
}

export function matchShareCard(feed: Feed, map: HTMLCanvasElement): HTMLCanvasElement {
  return frame("The Evening Match", feed.evening_ist, "low. Weak labels from maps. Not an official count.", (ctx) => {
    line(ctx, `Polar ${pct(feed.match.polar_share)}`, 430, 72, "#9ec5ff");
    line(ctx, `INSAT ${pct(feed.match.insat_share)}`, 530, 72, CLASS_COLOURS.agricultural);
    line(ctx, "share of today's fire cells each caught", 590, 32, "#9aa3b2");
    const mapHeight = 900;
    const mapWidth = Math.min(W - 80, (map.width / map.height) * mapHeight);
    ctx.drawImage(map, (W - mapWidth) / 2, 650, mapWidth, mapHeight);
  });
}

export function tomorrowShareCard(feed: Feed): HTMLCanvasElement {
  const t = feed.tomorrow;
  return frame(`Tomorrow in ${t.city}`, t.forecast_date, "low. A global model forecast, not the official one.", (ctx) => {
    line(ctx, t.pm25_24h_mean === null ? "PM2.5 not measured" : `PM2.5 about ${Math.round(t.pm25_24h_mean)}`, 560, 96);
    if (t.pm25_24h_mean !== null) line(ctx, "micrograms per cubic metre, 24 hour mean", 630, 32, "#9aa3b2");
    line(ctx, t.cpcb_category ? `CPCB: ${t.cpcb_category}` : "Category not measured", 780, 64, "#ffcf70");
    line(ctx, `Tonight's evening fire cells: ${t.evening_fire_cells}`, 940, 44);
    line(ctx, `School hybrid? ${t.school_hybrid}`, 1040, 40, "#9aa3b2");
    line(ctx, "CAMS forecast via Open-Meteo", 1140, 30, "#6f7888");
  });
}

export function heatleShareCard(feed: Feed, result: string): HTMLCanvasElement {
  return frame("Heatle", feed.evening_ist, "medium. Answers checked against satellite imagery.", (ctx) => {
    line(ctx, result, 700, 52);
    line(ctx, "One mystery hot spot. Six clues.", 820, 36, "#9aa3b2");
    line(ctx, "What is it?", 900, 44, "#ffb020");
  });
}

export async function shareCanvas(canvas: HTMLCanvasElement, name: string): Promise<void> {
  const blob = await new Promise<Blob | null>((resolve) => canvas.toBlob(resolve, "image/png"));
  if (!blob) return;
  const file = new File([blob], name, { type: "image/png" });
  if (navigator.canShare?.({ files: [file] })) {
    await navigator.share({ files: [file], title: "AgniNetra" });
    return;
  }
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = name;
  link.click();
  // Revoked later, not at once: some browsers start the download after click returns,
  // and an immediately revoked link saves nothing.
  window.setTimeout(() => URL.revokeObjectURL(url), 60_000);
}
