import { CLASS_COLOURS } from "./fire-map";
import type { Feed } from "./schema";

// A 9:16 image for an Instagram story or WhatsApp status. It carries the how sure note and
// "not an official count" like every screen does, and the credits in small type.

const W = 1080;
const H = 1920;

function line(ctx: CanvasRenderingContext2D, text: string, y: number, size: number, colour = "#e8edf5"): void {
  ctx.fillStyle = colour;
  ctx.font = `600 ${size}px system-ui, sans-serif`;
  ctx.textAlign = "center";
  ctx.fillText(text, W / 2, y);
}

export function matchShareCard(feed: Feed, map: HTMLCanvasElement): HTMLCanvasElement {
  const canvas = document.createElement("canvas");
  canvas.width = W;
  canvas.height = H;
  const ctx = canvas.getContext("2d");
  if (!ctx) return canvas;
  ctx.fillStyle = "#07090d";
  ctx.fillRect(0, 0, W, H);
  line(ctx, "AgniNetra", 140, 64, "#ffb020");
  line(ctx, "The Evening Match", 230, 56);
  line(ctx, feed.evening_ist, 300, 36, "#9aa3b2");

  const polar = feed.match.polar_share;
  const insat = feed.match.insat_share;
  line(ctx, `Polar ${polar === null ? "-" : Math.round(polar * 100) + "%"}`, 430, 72, "#9ec5ff");
  line(ctx, `INSAT ${insat === null ? "-" : Math.round(insat * 100) + "%"}`, 530, 72, CLASS_COLOURS.agricultural);
  line(ctx, "share of today's fire cells each caught", 590, 32, "#9aa3b2");

  const mapHeight = 900;
  const mapWidth = Math.min(W - 80, (map.width / map.height) * mapHeight);
  ctx.drawImage(map, (W - mapWidth) / 2, 650, mapWidth, mapHeight);

  line(ctx, "how sure: low. Weak labels from maps. Not an official count.", 1640, 30, "#ffcf70");
  ctx.font = "22px system-ui, sans-serif";
  ctx.fillStyle = "#6f7888";
  const credits = [
    "Data Source MOSDAC/SAC/ISRO. NASA FIRMS. Boundaries (c) OpenStreetMap contributors, ODbL.",
    "Fires shown per 11 km cell, never as individual fields.",
  ];
  credits.forEach((text, i) => ctx.fillText(text, W / 2, 1740 + i * 34));
  return canvas;
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
  URL.revokeObjectURL(url);
}
