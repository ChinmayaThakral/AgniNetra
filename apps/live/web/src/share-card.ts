import { plural } from "./dom";
import { type Mood, netuSvg } from "./netu";
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

export function heatleShareCard(feed: Feed, result: string, streak = 0): HTMLCanvasElement {
  return frame("Heatle", feed.evening_ist, "medium. Answers checked against satellite imagery.", (ctx) => {
    line(ctx, result, 700, 52);
    if (streak > 1) line(ctx, `Streak: ${streak} evenings`, 1000, 40, "#ffcf70");
    line(ctx, "One mystery hot spot. Six clues.", 820, 36, "#9aa3b2");
    line(ctx, "What is it?", 900, 44, "#ffb020");
  });
}

async function svgImage(svg: SVGSVGElement): Promise<{ image: HTMLImageElement; release: () => void }> {
  const text = new XMLSerializer().serializeToString(svg);
  const url = URL.createObjectURL(new Blob([text], { type: "image/svg+xml" }));
  const image = new Image();
  image.src = url;
  await image.decode();
  return { image, release: () => URL.revokeObjectURL(url) };
}

export async function petShareCard(mood: Mood, level: number, xp: number, wearing: string[]): Promise<HTMLCanvasElement> {
  const { image, release } = await svgImage(netuSvg(mood, 400, wearing));
  const canvas = frame("My Netu", `Level ${level}, ${plural(xp, "point")}`, "low. Weak labels from maps. Not an official count.", (ctx) => {
    ctx.drawImage(image, (W - 400) / 2, 420, 400, 480);
    line(ctx, wearing.length ? `Wearing ${wearing.join(", ")}` : "No items yet", 1020, 40);
    line(ctx, "Netu grows when I look, never when anything burns.", 1120, 34, "#9aa3b2");
  });
  release();
  return canvas;
}

export function wrappedShareCard(
  year: string,
  city: string,
  here: { bad_air_days: number; fire_hour_ist: string | null } | null,
  me: { daysIn: number; heatleSolved: number; heatleBest: number; swiped: number; level: number },
): HTMLCanvasElement {
  return frame(`Smog Wrapped ${year}`, city, "low. Forecast air and weak labels. Not an official count.", (ctx) => {
    let y = 480;
    if (here) {
      line(ctx, `${plural(here.bad_air_days, "day")} of poor air or worse`, y, 52, "#ffcf70");
      y += 90;
      line(ctx, here.fire_hour_ist ? `Fires near me started most at ${here.fire_hour_ist}` : "No fires near me this season", y, 40);
      y += 130;
    }
    line(ctx, `I checked in on ${plural(me.daysIn, "day")}`, y, 44);
    line(ctx, `Heatle: ${me.heatleSolved} solved, best streak ${me.heatleBest}`, y + 80, 40);
    line(ctx, `${plural(me.swiped, "hot spot")} labelled`, y + 160, 40);
    line(ctx, `My Netu: level ${me.level}`, y + 240, 44, "#ffb020");
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
