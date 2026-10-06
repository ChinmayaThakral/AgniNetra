import type { Label } from "./community";

// The pure part of Swipe, kept apart from the page so it can be tested: which way a drag
// counts as, and how a spot's record is put into words.

// A drag counts once it travels this far; shorter ones spring back, so a tap or a scroll
// never labels anything by accident.
export const THRESHOLD_PX = 90;

export function gesture(dx: number, dy: number, threshold = THRESHOLD_PX): Label | null {
  if (Math.hypot(dx, dy) < threshold) return null;
  if (-dy > Math.abs(dx)) return "unsure";
  if (Math.abs(dx) >= Math.abs(dy)) return dx > 0 ? "industry" : "not industry";
  return null;
}

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

// The months a spot burns in most, among the months the record covers, so a player can
// tell a source that burns through every observed month from a seasonal one.
export function busyMonths(byMonth: number[], observed: number[] = MONTHS.map((_, i) => i + 1)): string {
  const months = observed.filter((m) => m >= 1 && m <= 12);
  const counts = months.map((m) => [byMonth[m - 1] ?? 0, m - 1] as const);
  if (counts.every(([n]) => n === 0)) return "no detections in the months observed";
  const active = counts.filter(([n]) => n > 0).length;
  if (active === months.length) return `every observed month (${months.map((m) => MONTHS[m - 1]).join(", ")})`;
  const top = [...counts]
    .filter(([n]) => n > 0)
    .sort((a, b) => b[0] - a[0])
    .slice(0, 3)
    .map(([, i]) => MONTHS[i] ?? "");
  return `mostly ${top.join(", ")}; active in ${active} of the ${months.length} months observed`;
}

export function monthName(i: number): string {
  return MONTHS[i] ?? "";
}
