import { el, howSure } from "./dom";
import type { Feed } from "./schema";
import { shareCanvas, tomorrowShareCard } from "./share-card";

export interface CityAir {
  city: string;
  pm25: number | null;
  category: string | null;
}

// The chosen city's forecast, or the feed's Delhi default when the feed carries no list.
export function cityAir(feed: Feed, city: string): CityAir {
  const air = feed.air?.find((a) => a.city === city);
  if (air) return { city: air.city, pm25: air.pm25_24h_mean, category: air.cpcb_category };
  const t = feed.tomorrow;
  return { city: t.city, pm25: t.pm25_24h_mean, category: t.cpcb_category };
}

export function tomorrowCard(feed: Feed, city: string): HTMLElement {
  const t = feed.tomorrow;
  const air = cityAir(feed, city);
  const card = el("section", "card tomorrow");
  card.append(el("h2", "", `Tomorrow in ${air.city}`));
  card.append(el("p", "big", air.pm25 === null ? "PM2.5 forecast not measured" : `PM2.5 about ${Math.round(air.pm25)} µg/m³`));
  card.append(el("p", "", air.category ? `CPCB category: ${air.category}` : "Category not measured"));
  card.append(el("p", "", `Tonight's evening fire cells: ${t.evening_fire_cells}`));
  card.append(el("p", "muted", `Will school go hybrid? ${t.school_hybrid}.`));
  card.append(el("p", "muted small", `${t.source}. For ${t.forecast_date}.`));
  card.append(howSure("low", "A global model forecast, not the official forecast."));
  const share = el("button", "button share", "Share tomorrow");
  share.addEventListener("click", () => void shareCanvas(tomorrowShareCard(feed, air), `agninetra-tomorrow-${air.city}-${t.forecast_date}.png`));
  card.append(share);
  return card;
}
