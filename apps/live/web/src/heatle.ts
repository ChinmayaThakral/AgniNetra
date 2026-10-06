import { streakOf } from "./days";
import { el, plural } from "./dom";
import { award } from "./pet";
import type { Feed } from "./schema";
import { heatleShareCard, shareCanvas } from "./share-card";
import { HeatleRecord } from "./records";
import { recall, remember } from "./store";

// One game a day: the result is kept on this phone, so a replay neither changes it nor
// earns Netu more points, and the run of evenings played is the streak.

// Heatle: one mystery hot spot a day, six clues in turn. Every answer is a site whose
// identity was checked against imagery, and answers are categories, never company names.

const LAND_COVER_WORDS: Record<string, string> = {
  bare_sparse_vegetation: "bare ground or sparse plants",
  built_up: "built up land",
  cropland: "farmland",
  grassland: "grassland",
  shrubland: "shrubland",
  tree_cover: "trees",
};

function numberField(clue: Record<string, unknown>, key: string): number | null {
  const value = clue[key];
  return typeof value === "number" ? value : null;
}

function stringField(clue: Record<string, unknown>, key: string): string | null {
  const value = clue[key];
  return typeof value === "string" ? value : null;
}

export function clueText(clue: Record<string, unknown>): string {
  switch (clue.kind) {
    case "rhythm": {
      const night = numberField(clue, "night_share");
      return night === null ? "Daily rhythm not measured" : `Burns at night ${Math.round(night * 100)}% of the times it is seen`;
    }
    case "brightness": {
      const frp = numberField(clue, "median_frp_mw");
      return frp === null ? "Fire power not measured" : `Typical fire power: ${frp} megawatts`;
    }
    case "land_cover": {
      const value = stringField(clue, "value");
      return `The ground there: ${value ? (LAND_COVER_WORDS[value] ?? value.replace(/_/g, " ")) : "not measured"}`;
    }
    case "state":
      return `It is in ${stringField(clue, "value") ?? "a state not recorded"}`;
    case "persistence": {
      const count = numberField(clue, "detections_in_record");
      return count === null ? "History not measured" : `Seen ${plural(count, "time")} in our 2023 to 2026 record`;
    }
    case "image": {
      const span = numberField(clue, "span_km");
      return span === null ? "A view from space" : `A view from space, ${span} km across`;
    }
    case "place": {
      const state = stringField(clue, "state");
      return state ? `It is in ${state}. Its 11 km cell is now ringed on the map` : "Its place is now ringed on the map";
    }
    default:
      return "A clue this version cannot show";
  }
}

export function heatleCard(feed: Feed, onPlace: (centre: [number, number]) => void): HTMLElement {
  const game = feed.heatle;
  const card = el("section", "card heatle");
  card.append(el("h2", "", "Heatle"), el("p", "muted", "One mystery hot spot. Six clues. What is it?"));
  const clues = el("ol", "clues");
  const choices = el("div", "choices");
  const result = el("p", "result");
  const more = el("button", "button", "Next clue");
  let shown = 0;
  let done = false;

  const reveal = (): void => {
    const clue = game.clues[shown];
    if (!clue) return;
    const item = el("li", "", clueText(clue));
    const src = stringField(clue, "src");
    // Only the app's own chips are ever shown; the feed validator refuses anything else.
    if (clue.kind === "image" && src && /^chips\/[a-z0-9_]+\.webp$/.test(src)) {
      const picture = el("img", "chip heatle-chip");
      picture.src = src;
      picture.alt = `${clueText(clue)}, of the mystery site`;
      picture.width = 256;
      picture.height = 256;
      item.append(picture);
      const acquired = stringField(clue, "acquired");
      if (acquired) item.append(el("span", "muted small chip-credit", `Sentinel-2, ${acquired}. Contains modified Copernicus Sentinel data.`));
    }
    clues.append(item);
    if (clue.kind === "place") {
      const centre = clue.centre;
      if (Array.isArray(centre) && typeof centre[0] === "number" && typeof centre[1] === "number") {
        onPlace([centre[0], centre[1]]);
      }
    }
    shown += 1;
    more.disabled = shown >= game.clues.length || done;
  };

  const today = feed.evening_ist;
  let played = recall("heatle", (v) => HeatleRecord.parse(v), {});

  const finish = (solved: boolean, clue: number): void => {
    done = true;
    more.disabled = true;
    const streak = streakOf(played, today);
    result.textContent =
      (solved ? `Solved on clue ${clue} of ${game.clues.length}. It is a ${game.answer}.` : `Not this time. It is a ${game.answer}.`) +
      (streak > 1 ? ` Streak: ${streak} evenings.` : "");
    const summary = solved ? `Solved on clue ${clue} of ${game.clues.length}` : "Not solved today";
    const share = el("button", "button share", "Share my Heatle");
    share.addEventListener("click", () => void shareCanvas(heatleShareCard(feed, summary, streak), `heatle-${today}.png`));
    card.append(share);
  };

  for (const choice of game.choices) {
    const button = el("button", "choice", choice);
    button.addEventListener("click", () => {
      if (done) return;
      const right = choice === game.answer;
      played = { ...played, [today]: { solved: right, clue: shown } };
      remember("heatle", played);
      award(right ? "heatleSolved" : "heatlePlayed");
      button.classList.add(right ? "right" : "wrong");
      finish(right, shown);
    });
    choices.append(button);
  }
  more.addEventListener("click", reveal);
  reveal();
  const before = played[today];
  if (before) {
    while (shown < Math.max(before.clue, 1)) reveal();
    finish(before.solved, before.clue);
  }
  card.append(clues, more, choices, result);
  card.append(el("p", "muted small", "Answers come from sites checked against satellite imagery."));
  return card;
}
