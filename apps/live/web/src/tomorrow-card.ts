import { el, howSure } from "./dom";
import type { Feed } from "./schema";
import { shareCanvas, tomorrowShareCard } from "./share-card";

export function tomorrowCard(feed: Feed): HTMLElement {
  const t = feed.tomorrow;
  const card = el("section", "card tomorrow");
  card.append(el("h2", "", `Tomorrow in ${t.city}`));
  card.append(
    el(
      "p",
      "big",
      t.pm25_24h_mean === null ? "PM2.5 forecast not measured" : `PM2.5 about ${Math.round(t.pm25_24h_mean)} µg/m³`,
    ),
  );
  card.append(el("p", "", t.cpcb_category ? `CPCB category: ${t.cpcb_category}` : "Category not measured"));
  card.append(el("p", "", `Tonight's evening fire cells: ${t.evening_fire_cells}`));
  card.append(el("p", "muted", `Will school go hybrid? ${t.school_hybrid}.`));
  card.append(el("p", "muted small", `${t.source}. For ${t.forecast_date}.`));
  card.append(howSure("low", "A global model forecast, not the official Delhi forecast."));
  const share = el("button", "button share", "Share tomorrow");
  share.addEventListener("click", () => void shareCanvas(tomorrowShareCard(feed), `agninetra-tomorrow-${t.forecast_date}.png`));
  card.append(share);
  return card;
}
