import { z } from "zod";
import { bestStreak } from "./days";
import { el, howSure, percent, plural } from "./dom";
import { levelOf, petState } from "./pet";
import { BAD_AIR, HeatleRecord, SwipeRecord, VisitRecord } from "./records";
import { shareCanvas, wrappedShareCard } from "./share-card";
import { recall } from "./store";

// Smog Wrapped. The season's numbers for everyone come from the pipeline; the player's own
// come from this phone and are never sent anywhere, rule 6.

export const Season = z.object({
  schema: z.literal("agninetra-season/1"),
  first_evening: z.string().nullable(),
  last_evening: z.string().nullable(),
  evenings: z.number().int().min(0),
  evening_fire_cells: z.number().int().min(0),
  insat_share_mean: z.number().min(0).max(1).nullable(),
  polar_share_mean: z.number().min(0).max(1).nullable(),
  cities: z.array(
    z.object({
      city: z.string(),
      bad_air_days: z.number().int().min(0),
      cells_near: z.number().int().min(0),
      fire_hour_ist: z.string().nullable(),
    }),
  ),
});
export type Season = z.infer<typeof Season>;

// Wrapped shows in December, or as a preview when the address carries ?wrapped.
export function wrappedTime(day: string, search: string): boolean {
  return day.slice(5, 7) === "12" || new URLSearchParams(search).has("wrapped");
}

export interface Personal {
  daysIn: number;
  badAirDays: number;
  heatlePlayed: number;
  heatleSolved: number;
  heatleBest: number;
  swiped: number;
  level: number;
}

export function personal(): Personal {
  const visits = recall("visits", (v) => VisitRecord.parse(v), {});
  const heatle = recall("heatle", (v) => HeatleRecord.parse(v), {});
  const swipe = recall("swipe", (v) => SwipeRecord.parse(v), {});
  return {
    daysIn: Object.keys(visits).length,
    badAirDays: Object.values(visits).filter((c) => c !== null && BAD_AIR.includes(c)).length,
    heatlePlayed: Object.keys(heatle).length,
    heatleSolved: Object.values(heatle).filter((d) => d.solved).length,
    heatleBest: bestStreak(heatle),
    swiped: Object.keys(swipe).length,
    level: levelOf(petState().xp),
  };
}

export function wrappedCard(season: Season, city: string): HTMLElement {
  const card = el("section", "card wrapped");
  const year = (season.last_evening ?? "").slice(0, 4);
  const here = season.cities.find((c) => c.city === city);
  const me = personal();
  card.append(el("h2", "", `Smog Wrapped ${year}`));
  if (here) {
    card.append(el("h3", "", `For ${city}`));
    card.append(
      el("p", "", `${plural(here.bad_air_days, "day")} forecast at poor air or worse.`),
      el("p", "", `${plural(here.cells_near, "fire cell")} within 300 km over the season.`),
      el("p", "", here.fire_hour_ist ? `Fires near you were most often first seen at ${here.fire_hour_ist} IST.` : "No fire cells near you this season."),
    );
  }
  card.append(el("h3", "", "The season"));
  card.append(
    el("p", "", `${plural(season.evenings, "evening")} watched, ${season.first_evening ?? "not measured"} to ${season.last_evening ?? "not measured"}.`),
    el("p", "", `INSAT-3DS caught ${percent(season.insat_share_mean)} of the fire cells on an average evening, the polar satellites ${percent(season.polar_share_mean)}.`),
  );
  card.append(el("h3", "", "You"));
  card.append(
    el("p", "", `You checked in on ${plural(me.daysIn, "day")}, ${me.badAirDays} of them with poor air or worse in your city.`),
    el("p", "", `Heatle: ${me.heatleSolved} solved of ${me.heatlePlayed} played, best streak ${me.heatleBest}.`),
    el("p", "", `You labelled ${plural(me.swiped, "hot spot")}, and your Netu reached level ${me.level}.`),
  );
  card.append(howSure("low", "Forecast air and weak labels. Not an official count."));
  const share = el("button", "button share", "Share my Wrapped");
  share.addEventListener("click", () => void shareCanvas(wrappedShareCard(year, city, here ?? null, me), `smog-wrapped-${year}.png`));
  card.append(share);
  return card;
}
