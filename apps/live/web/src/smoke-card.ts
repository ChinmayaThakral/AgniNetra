import { el, howSure } from "./dom";
import { CLASS_LABELS } from "./fire-map";
import type { Feed } from "./schema";
import { CORRIDOR_KM, type Point, upwindSources } from "./upwind";

// "What's that smoke?" The location is used on this phone only and never sent anywhere.

export function smokeCard(feed: Feed, onTrace: (path: Point[]) => void): { card: HTMLElement; trace: (origin: Point) => void } {
  const card = el("section", "card smoke");
  card.append(el("h2", "", "What's that smoke?"));
  const output = el("div", "smoke-output");

  const trace = (origin: Point): void => {
    output.replaceChildren();
    if (!feed.wind) {
      output.append(el("p", "muted", "Wind is only carried for tonight's feed, so this evening cannot be traced."));
      return;
    }
    const { path, sources } = upwindSources(origin, feed.wind, feed.cells);
    onTrace(path);
    if (sources.length === 0) {
      output.append(el("p", "", "No fire cells found upwind in the last six hours."));
      return;
    }
    output.append(el("p", "", `Fire cells upwind of you, within ${CORRIDOR_KM} km of the path the air took:`));
    const list = el("ul", "sources");
    for (const source of sources.slice(0, 6)) {
      const item = el(
        "li",
        "",
        `${CLASS_LABELS[source.cell.class]}, ${source.distanceKm} km away, air from there about ${source.hoursAgo} h ago`,
      );
      item.append(howSure(source.cell.how_sure));
      list.append(item);
    }
    output.append(list);
  };

  const locate = el("button", "button", "Use my location");
  locate.addEventListener("click", () => {
    if (!("geolocation" in navigator)) {
      output.replaceChildren(el("p", "muted", "This browser cannot share a location. Tap the map instead."));
      return;
    }
    navigator.geolocation.getCurrentPosition(
      (position) => trace([position.coords.longitude, position.coords.latitude]),
      () => output.replaceChildren(el("p", "muted", "Location was not shared. Tap the map instead.")),
      { maximumAge: 600000, timeout: 15000 },
    );
  });
  card.append(
    el("p", "muted", "Your location stays on this phone. Or tap anywhere on the map."),
    locate,
    output,
    el("p", "muted small", feed.wind ? `Wind: ${feed.wind.source}.` : "No wind in this feed."),
  );
  return { card, trace };
}
