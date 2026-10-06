import { z } from "zod";
import { streakOf } from "./days";
import { el, plural } from "./dom";
import { award } from "./pet";
import type { Feed } from "./schema";
import { heatleShareCard, shareCanvas } from "./share-card";
import { HeatleRecord } from "./records";
import { recall, remember } from "./store";

// Heatle: one mystery hot spot, six clues, each explained as it appears. Every answer is
// a site whose identity was checked against imagery, and answers are categories, never
// company names. A wrong guess teaches and opens the next clue rather than ending the
// round. The daily puzzle keeps the streak; practice rounds over the other verified
// sites can be played as often as a player likes.

export const Puzzle = z.object({
  clues: z.array(z.record(z.string(), z.unknown())),
  answer: z.string(),
  choices: z.array(z.string()),
});
export type Puzzle = z.infer<typeof Puzzle>;

export const HeatlePack = z.object({
  schema: z.literal("agninetra-heatle/1"),
  credit: z.string().nullable().optional(),
  puzzles: z.array(Puzzle).min(1),
});
export type HeatlePack = z.infer<typeof HeatlePack>;

const LAND_COVER_WORDS: Record<string, string> = {
  bare_sparse_vegetation: "bare ground or sparse plants",
  built_up: "built up land",
  cropland: "farmland",
  grassland: "grassland",
  shrubland: "shrubland",
  tree_cover: "trees",
};

// What each kind of site is like, said when it is the answer and when it is a wrong guess.
export const ABOUT: Record<string, string> = {
  "steel or iron plant":
    "Steel and sponge iron plants run their furnaces day and night. They are large and bright, and from space show long sheds, stacks and heaps of ore.",
  "coal mine":
    "Coal mines show dark open pits and stepped terraces from space. Exposed coal can smoulder for years, so the heat comes back again and again, day and night, at modest power.",
  "brick kiln":
    "Brick kilns are small oval or rectangular kilns, often in farmland near towns, and they fire in the dry season rather than all year.",
  "power plant":
    "Coal power stations have cooling towers, coal yards and grey ash ponds, and usually sit beside a river or reservoir.",
  "gas flare":
    "Gas flares burn day and night at oil and gas fields: a single very hot point with little built around it.",
  "other industry":
    "Cement works, refineries, chemical plants and smelters: industrial heat that is not steel, a mine, bricks or power.",
  "cannot tell": "Sometimes the clues really do not settle it. Look again at the night share and the pictures.",
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
    case "spread": {
      const spread = numberField(clue, "spread_m");
      return spread === null ? "Size not measured" : `The hot spots there spread over about ${(spread / 1000).toFixed(1)} km`;
    }
    case "place": {
      const state = stringField(clue, "state");
      return state ? `It is in ${state}. Its 11 km cell is now ringed on the map` : "Its place is now ringed on the map";
    }
    default:
      return "A clue this version cannot show";
  }
}

// What a clue tells a player, so each one teaches something about reading the sky.
export function clueLesson(clue: Record<string, unknown>): string {
  switch (clue.kind) {
    case "rhythm": {
      const night = numberField(clue, "night_share");
      if (night === null) return "";
      if (night >= 0.6) return "Crop burning happens in the afternoon. Heat seen mostly at night points to something that never switches off: a furnace, a kiln, a flare or a burning coal seam.";
      if (night <= 0.3) return "Mostly daytime heat, which is how farm fires and daytime industry behave.";
      return "Heat by day and by night: a source that runs often, but not always.";
    }
    case "brightness": {
      const frp = numberField(clue, "median_frp_mw");
      if (frp === null) return "";
      if (frp >= 20) return "That is a lot of heat. Large, steady heat comes from steel plants, power stations and flares.";
      if (frp <= 5) return "Modest heat, the size of a small kiln, a smouldering mine or a field fire.";
      return "Medium heat, where many kinds of industry sit.";
    }
    case "land_cover": {
      const value = stringField(clue, "value");
      if (value === "built_up") return "Built up land means towns and industrial estates.";
      if (value === "bare_sparse_vegetation") return "Bare ground is typical of mines, quarries and slag heaps.";
      if (value === "cropland") return "Farmland around it, but the earlier clues decide whether this is a farm fire.";
      return "Little is built around it. Remote heat is often a mine or a flare.";
    }
    case "image":
      return numberField(clue, "span_km") !== null && (numberField(clue, "span_km") ?? 0) > 5
        ? "Zoomed out: is it alone among fields, or part of a mining belt or an industrial town?"
        : "Look for long sheds and stacks for a plant, dark pits and terraces for a mine, or one lone hot pad for a flare.";
    case "state":
      return "Some states are known for certain industries: Jharkhand and Odisha for coal and steel, Gujarat and Assam for oil and gas.";
    case "spread": {
      const spread = numberField(clue, "spread_m");
      if (spread === null) return "";
      return spread >= 2000
        ? "A wide hot area is a big site: a mine with many working faces, or a large steel works."
        : "A tight hot area points to one furnace, one stack or a single flare.";
    }
    case "persistence":
      return "Seen many times at the same spot, so it is a fixed source, not a one off fire.";
    case "place":
      return "Now you know where it is. Did the clues point the same way?";
    default:
      return "";
  }
}

export function clueItem(clue: Record<string, unknown>): HTMLLIElement {
  const item = el("li", "");
  item.append(el("span", "clue-text", clueText(clue)));
  const src = stringField(clue, "src");
  // Only the app's own chips are ever shown; the feed validator refuses anything else.
  if (clue.kind === "image" && src && /^chips\/(q\/)?[a-z0-9_]+\.webp$/.test(src)) {
    const picture = el("img", "chip heatle-chip");
    picture.src = src;
    picture.alt = `${clueText(clue)}, of the mystery site`;
    picture.width = 256;
    picture.height = 256;
    item.append(picture);
    const acquired = stringField(clue, "acquired");
    if (acquired) item.append(el("span", "muted small chip-credit", `Sentinel-2, ${acquired}. Contains modified Copernicus Sentinel data.`));
  }
  const lesson = clueLesson(clue);
  if (lesson) item.append(el("span", "clue-lesson", lesson));
  return item;
}

function pickOther(pack: HeatlePack, current: Puzzle): Puzzle {
  const others = pack.puzzles.filter((p) => p !== current && JSON.stringify(p.clues) !== JSON.stringify(current.clues));
  const pool = others.length ? others : pack.puzzles;
  return pool[Math.floor(Math.random() * pool.length)] ?? current;
}

export function heatleCard(feed: Feed, pack: HeatlePack | null, onPlace: (centre: [number, number]) => void): HTMLElement {
  const card = el("section", "card heatle");
  const today = feed.evening_ist;
  let played = recall("heatle", (v) => HeatleRecord.parse(v), {});

  const play = (puzzle: Puzzle, daily: boolean, earlier?: { solved: boolean; clue: number }): void => {
    card.replaceChildren(
      el("h2", "", daily ? "Heatle" : "Heatle practice"),
      el("p", "muted", daily ? "Today's mystery hot spot. Clues come one at a time, each with what it tells you. Guess whenever you like." : "Another verified site. Learn how each clue points to the answer."),
    );
    const clues = el("ol", "clues");
    const feedback = el("p", "heatle-feedback", "");
    const choices = el("div", "choices");
    const more = el("button", "button", "Next clue");
    const after = el("div", "choices heatle-after");
    let shown = 0;
    let done = false;
    let wrong = 0;

    const reveal = (): void => {
      const clue = puzzle.clues[shown];
      if (!clue) return;
      clues.append(clueItem(clue));
      if (clue.kind === "place") {
        const centre = clue.centre;
        if (Array.isArray(centre) && typeof centre[0] === "number" && typeof centre[1] === "number") onPlace([centre[0], centre[1]]);
      }
      shown += 1;
      more.disabled = shown >= puzzle.clues.length || done;
    };

    const finish = (solved: boolean): void => {
      const usedClues = shown;
      done = true;
      for (const button of choices.querySelectorAll("button")) button.disabled = true;
      while (shown < puzzle.clues.length) reveal();
      more.disabled = true;
      const about = ABOUT[puzzle.answer] ?? "";
      if (earlier) feedback.textContent = `${earlier.solved ? "You solved today's Heatle" : "Today's Heatle is done"}: it is a ${puzzle.answer}. ${about}`;
      else
        feedback.textContent = solved
          ? `Yes, it is a ${puzzle.answer}, found with ${plural(usedClues, "clue")}${wrong ? ` and ${plural(wrong, "wrong guess", "wrong guesses")}` : ""}. ${about}`
          : `It is a ${puzzle.answer}. ${about}`;
      feedback.className = solved ? "heatle-feedback right" : "heatle-feedback";
      after.replaceChildren();
      if (daily) {
        const streak = streakOf(played, today);
        if (streak > 1) after.append(el("span", "muted small", `Streak: ${plural(streak, "evening")}`));
        const share = el("button", "button share", "Share my Heatle");
        const summary = solved ? `Solved on clue ${earlier ? earlier.clue : usedClues} of ${puzzle.clues.length}` : "Not solved today";
        share.addEventListener("click", () => void shareCanvas(heatleShareCard(feed, summary, streak), `heatle-${today}.png`));
        after.append(share);
      }
      if (pack) {
        const next = el("button", "button", "Play another site");
        next.addEventListener("click", () => play(pickOther(pack, puzzle), false));
        after.append(next);
      }
    };

    const record = (solved: boolean): void => {
      if (!daily || played[today]) return;
      played = { ...played, [today]: { solved, clue: Math.max(shown, 1) } };
      remember("heatle", played);
      award(solved ? "heatleSolved" : "heatlePlayed");
    };

    for (const choice of puzzle.choices) {
      const button = el("button", "choice", choice);
      button.addEventListener("click", () => {
        if (done) return;
        if (choice === puzzle.answer) {
          button.classList.add("right");
          record(true);
          if (!daily) award("heatlePlayed");
          finish(true);
          return;
        }
        wrong += 1;
        button.classList.add("wrong");
        button.disabled = true;
        const why = ABOUT[choice] ?? "";
        if (shown >= puzzle.clues.length) {
          record(false);
          finish(false);
          return;
        }
        feedback.textContent = `Not a ${choice}. ${why} Here is another clue.`;
        feedback.className = "heatle-feedback";
        reveal();
      });
      choices.append(button);
    }
    more.addEventListener("click", reveal);
    card.append(clues, more, choices, feedback, after);
    card.append(el("p", "muted small", "Answers come from sites checked against satellite imagery."));
    reveal();
    if (earlier) finish(earlier.solved);
  };

  const before = played[today];
  play(feed.heatle, true, before);
  return card;
}
