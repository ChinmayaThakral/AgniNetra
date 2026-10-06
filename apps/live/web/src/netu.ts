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

// What Netu wears, unlocked by playing. Drawn after the eye so a cap or a scarf sits on top.
// Static markup from this file only, like the rest of Netu.
const WEAR: Record<string, string> = {
  "cricket cap": '<path d="M31 36 Q48 16 66 34 Z" fill="#1e3a8a"/><path d="M60 33 L82 38 L80 41 L58 37 Z" fill="#1e3a8a"/>',
  sunglasses: '<circle cx="50" cy="59" r="15" fill="#111" opacity="0.9"/><path d="M35 57 L22 54 M65 57 L78 54" stroke="#111" stroke-width="3" stroke-linecap="round"/><circle cx="45" cy="54" r="3" fill="#fff" opacity="0.6"/>',
  "smog scarf": '<path d="M19 88 Q50 100 81 88 L81 96 Q50 108 19 96 Z" fill="#94a3b8"/><path d="M30 92 L30 100 M44 95 L44 103 M58 95 L58 103 M70 92 L70 100" stroke="#64748b" stroke-width="2"/>',
  "umpire's hat": '<ellipse cx="50" cy="31" rx="27" ry="5" fill="#f1f5f9"/><path d="M36 31 Q36 15 50 15 Q64 15 64 31 Z" fill="#f1f5f9"/><path d="M36 28 L64 28" stroke="#1f2937" stroke-width="2"/>',
  "golden eye": '<circle cx="50" cy="58" r="15" fill="none" stroke="#f59e0b" stroke-width="3"/>',
};

export function netuSvg(mood: Mood, size = 88, wearing: string[] = []): SVGSVGElement {
  const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  svg.setAttribute("viewBox", "0 0 100 120");
  svg.setAttribute("width", String(size));
  svg.setAttribute("height", String((size * 120) / 100));
  svg.setAttribute("role", "img");
  svg.setAttribute("aria-label", `Netu, ${mood}${wearing.length ? `, wearing ${wearing.join(", ")}` : ""}`);
  // Static markup from this file only; no feed text is interpolated into it.
  svg.innerHTML =
    '<defs><radialGradient id="flame" cx="50%" cy="70%" r="60%">' +
    '<stop offset="0%" stop-color="#ffe08a"/><stop offset="60%" stop-color="#ff8a2b"/>' +
    '<stop offset="100%" stop-color="#e2361c"/></radialGradient></defs>' +
    '<path d="M50 4 C62 30 88 44 84 78 C81 104 64 116 50 116 C36 116 19 104 16 78 ' +
    'C13 52 34 42 38 20 C44 32 50 30 50 4 Z" fill="url(#flame)"/>' +
    EYES[mood] +
    wearing.map((item) => WEAR[item] ?? "").join("");
  return svg;
}
