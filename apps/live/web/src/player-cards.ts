import { el, percent } from "./dom";
import type { Feed } from "./schema";

// The two teams. Facts come from the report: pixel sizes from the sensor specifications
// it cites, and the six polar look times from its own measurement over 601941 detections,
// in local solar time. Today's numbers come from the feed.

interface Player {
  team: string;
  who: string;
  sees: string;
  looks: string;
  share: number | null;
  last: string | null;
}

export function playerCards(feed: Feed): HTMLElement {
  const players: Player[] = [
    {
      team: "Polar satellites",
      who: "VIIRS on Suomi NPP, NOAA-20 and NOAA-21; MODIS on Terra and Aqua",
      sees: "Sharp eyes: 375 m pixels for VIIRS, 1 km for MODIS",
      looks: "Six fixed looks a day, near 01:42, 02:48, 09:54, 13:12, 13:54 and 21:18 local solar time",
      share: feed.match.polar_share,
      last: feed.match.polar_last_seen_ist,
    },
    {
      team: "INSAT-3DS",
      who: "India's own geostationary weather satellite",
      sees: "Blurry eyes: 4 km pixels",
      looks: "Never looks away: a picture every 30 minutes, day and night",
      share: feed.match.insat_share,
      last: feed.match.insat_last_seen_ist,
    },
  ];
  const wrap = el("section", "card players");
  wrap.append(el("h2", "", "The players"));
  const grid = el("div", "player-grid");
  for (const p of players) {
    const card = el("article", "player");
    card.append(
      el("h3", "", p.team),
      el("p", "small", p.who),
      el("p", "", p.sees),
      el("p", "", p.looks),
      el("p", "stat", `Today: ${percent(p.share)} of fire cells, last seen ${p.last ?? "not today"}`),
    );
    grid.append(card);
  }
  wrap.append(grid);
  return wrap;
}

export function commentaryList(feed: Feed): HTMLElement {
  const list = el("ol", "commentary");
  for (const line of feed.commentary) list.append(el("li", "", line.text));
  return list;
}
