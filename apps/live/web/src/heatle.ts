import { el } from "./dom";
import type { Feed } from "./schema";

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
      return count === null ? "History not measured" : `Seen ${count} times in our 2023 to 2026 record`;
    }
    case "place":
      return "Its place is now ringed on the map";
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
    clues.append(el("li", "", clueText(clue)));
    if (clue.kind === "place") {
      const centre = clue.centre;
      if (Array.isArray(centre) && typeof centre[0] === "number" && typeof centre[1] === "number") {
        onPlace([centre[0], centre[1]]);
      }
    }
    shown += 1;
    more.disabled = shown >= game.clues.length || done;
  };

  for (const choice of game.choices) {
    const button = el("button", "choice", choice);
    button.addEventListener("click", () => {
      if (done) return;
      done = true;
      more.disabled = true;
      const right = choice === game.answer;
      button.classList.add(right ? "right" : "wrong");
      result.textContent = right
        ? `Solved on clue ${shown} of ${game.clues.length}. It is a ${game.answer}.`
        : `Not this time. It is a ${game.answer}.`;
    });
    choices.append(button);
  }
  more.addEventListener("click", reveal);
  reveal();
  card.append(clues, more, choices, result);
  card.append(el("p", "muted small", "Answers come from sites checked against satellite imagery."));
  return card;
}
