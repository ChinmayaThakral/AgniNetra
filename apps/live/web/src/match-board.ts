import { el, howSure, percent } from "./dom";
import { commentaryList } from "./player-cards";
import type { Feed } from "./schema";

// The Evening Match. Scores are shares of the day's fire cells each satellite caught,
// never counts of fires.

export function matchBoard(feed: Feed): HTMLElement {
  const { match } = feed;
  const board = el("section", "card match");
  board.append(el("h2", "", "The Evening Match"));
  board.append(el("p", "muted", `${feed.evening_ist}, fires seen ${match.window_ist} IST`));

  const teams = el("div", "teams");
  const polar = el("div", "team polar");
  polar.append(el("div", "team-name", "Polar satellites"), el("div", match.polar_share === null ? "score unmeasured" : "score", percent(match.polar_share)));
  polar.append(
    el(
      "div",
      "status",
      match.polar_last_seen_ist ? `all out at ${match.polar_last_seen_ist}` : "did not bat",
    ),
  );
  const insat = el("div", "team insat");
  insat.append(el("div", "team-name", "INSAT-3DS"), el("div", match.insat_share === null ? "score unmeasured" : "score", percent(match.insat_share)));
  insat.append(
    el(
      "div",
      "status",
      match.insat_last_seen_ist ? `last catch ${match.insat_last_seen_ist}` : "not yet batting",
    ),
  );
  teams.append(polar, el("div", "versus", "vs"), insat);
  board.append(teams);

  const overs = el("ol", "overs");
  for (const over of match.overs) {
    const item = el("li", over.insat_new ? "over new" : "over");
    item.append(el("span", "over-time", over.over), el("span", over.insat_share === null ? "over-score unmeasured" : "over-score", percent(over.insat_share)));
    item.title = `After the ${over.over} over: INSAT ${percent(over.insat_share)}, polar ${percent(over.polar_share)}`;
    overs.append(item);
  }
  board.append(el("h3", "", "Over by over, INSAT share"), overs);
  board.append(el("h3", "", "Commentary"), commentaryList(feed));
  board.append(howSure("low", "Share of 11 km fire cells caught. Weak labels. Not an official count."));
  return board;
}
