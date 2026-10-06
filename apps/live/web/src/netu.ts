import type { Feed } from "./schema";

// Netu, a small flame with one big eye. Its mood is read from the feed and nothing else,
// and it is never excited by fire: worried when the air or the smoke is bad, resting when
// the sky is quiet or the air clean, watchful otherwise.

export type Mood = "watchful" | "worried" | "resting";

// With a city chosen, Netu follows that city's air tomorrow: calm in clean air, watchful
// in moderate, worried from poor upwards. Without one, it reads the evening's lines.
const AIR_MOOD: Record<string, Mood> = {
  Good: "resting",
  Satisfactory: "resting",
  Moderate: "watchful",
  Poor: "worried",
  "Very Poor": "worried",
  Severe: "worried",
};

export function moodOf(feed: Feed, city?: string): Mood {
  const category = city ? feed.air?.find((a) => a.city === city)?.cpcb_category : undefined;
  if (category) return AIR_MOOD[category] ?? "watchful";
  const said = new Set(feed.netu.map((line) => line.template));
  if (said.has("worried")) return "worried";
  if (said.has("quiet")) return "resting";
  return "watchful";
}

const EYES: Record<Mood, string> = {
  watchful: '<circle cx="50" cy="58" r="13" fill="#fff"/><circle cx="52" cy="60" r="6" fill="#111"/>',
  worried:
    '<circle cx="50" cy="60" r="12" fill="#fff"/><circle cx="50" cy="63" r="5" fill="#111"/>' +
    '<path d="M36 44 L62 50" stroke="#111" stroke-width="3" stroke-linecap="round"/>',
  resting: '<path d="M38 60 Q50 68 62 60" stroke="#111" stroke-width="4" fill="none" stroke-linecap="round"/>',
};

export function netuSvg(mood: Mood, size = 88): SVGSVGElement {
  const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  svg.setAttribute("viewBox", "0 0 100 120");
  svg.setAttribute("width", String(size));
  svg.setAttribute("height", String((size * 120) / 100));
  svg.setAttribute("role", "img");
  svg.setAttribute("aria-label", `Netu, ${mood}`);
  // Static markup from this file only; no feed text is interpolated into it.
  svg.innerHTML =
    '<defs><radialGradient id="flame" cx="50%" cy="70%" r="60%">' +
    '<stop offset="0%" stop-color="#ffe08a"/><stop offset="60%" stop-color="#ff8a2b"/>' +
    '<stop offset="100%" stop-color="#e2361c"/></radialGradient></defs>' +
    '<path d="M50 4 C62 30 88 44 84 78 C81 104 64 116 50 116 C36 116 19 104 16 78 ' +
    'C13 52 34 42 38 20 C44 32 50 30 50 4 Z" fill="url(#flame)"/>' +
    EYES[mood];
  return svg;
}
