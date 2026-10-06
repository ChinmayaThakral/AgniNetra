import { z } from "zod";
import { el, howSure, plural } from "./dom";
import { award } from "./pet";
import { SwipeRecord } from "./records";
import { shareCanvas, swipeShareCard } from "./share-card";
import { recall, remember } from "./store";
import { type Answer, type Given, gesture, goldScore, queue, type SwipeItem } from "./swipe-logic";

// Swipe: label recurring hot spots from Sentinel-2 pictures. Industrial and flare
// candidates only, from night-heavy persistent sources, so no field is ever shown, rule 1.
// Answers stay on this phone, D139, and every one of them earns Netu experience.

export const SwipePack = z.object({
  schema: z.literal("agninetra-swipe/1"),
  credit: z.string().min(1),
  close_span_km: z.number().positive(),
  items: z.array(
    z.object({
      id: z.string().regex(/^s[0-9a-f]{10}$/),
      chip: z.string().regex(/^chips\/s[0-9a-f]{10}\.webp$/),
      scene: z.string(),
      acquired: z.string(),
      gold: z.enum(["factory", "flare"]).nullable(),
    }),
  ),
});
export type SwipePack = z.infer<typeof SwipePack>;


const CHOICES: [Answer, string][] = [
  ["unsure", "← Not sure"],
  ["flare", "↑ Flare"],
  ["factory", "Factory →"],
];

export function swipeCard(pack: SwipePack, today: string): HTMLElement {
  const card = el("section", "card swipe");
  card.append(el("h2", "", "Swipe: what is this hot spot?"));
  card.append(
    el(
      "p",
      "muted",
      "Each picture is a place that burns again and again, mostly at night. Swipe right for a factory, any industry or mine, up for a gas flare, left if you are not sure.",
    ),
  );
  const stage = el("div", "swipe-stage");
  stage.tabIndex = 0;
  stage.setAttribute("aria-label", "Picture to label. Use the buttons, or the left, up and right arrow keys.");
  const picture = el("img", "chip");
  picture.width = 256;
  picture.height = 256;
  stage.append(picture);
  const caption = el("p", "muted small", "");
  const buttons = el("div", "choices swipe-choices");
  const status = el("p", "small", "");
  let answers: Record<string, Given> = recall("swipe", (v) => SwipeRecord.parse(v), {});
  let order = queue(pack.items, answers, Number(today.replace(/-/g, "")));
  let current: SwipeItem | undefined;

  const describe = (): void => {
    const score = goldScore(pack.items, answers);
    const done = Object.keys(answers).length;
    status.textContent =
      `You have looked at ${done} of ${pack.items.length} places.` +
      (score.judged ? ` On sites already checked in imagery, your eye was right ${score.right} of ${plural(score.judged, "time")}.` : "");
  };

  const show = (): void => {
    current = order[0];
    if (!current) {
      stage.remove();
      buttons.remove();
      caption.textContent = "You have looked at every place. Each answer helps find the heat sources the maps are missing.";
      return;
    }
    picture.src = current.chip;
    picture.alt = `Satellite picture of a recurring hot spot, ${pack.close_span_km} km across, seen ${current.acquired}`;
    caption.textContent = `${pack.close_span_km} km across, seen ${current.acquired}. ${pack.credit}`;
    const next = order[1];
    if (next) new Image().src = next.chip;
  };

  const answer = (a: Answer): void => {
    if (!current) return;
    answers = { ...answers, [current.id]: { a, at: new Date().toISOString() } };
    remember("swipe", answers);
    award(current.gold !== null && a === current.gold ? "swipeGoldRight" : "swipe");
    order = order.slice(1);
    describe();
    show();
  };

  for (const [a, text] of CHOICES) {
    const button = el("button", "choice", text);
    button.addEventListener("click", () => answer(a));
    buttons.append(button);
  }
  let start: [number, number] | null = null;
  stage.addEventListener("pointerdown", (event) => {
    start = [event.clientX, event.clientY];
  });
  stage.addEventListener("pointerup", (event) => {
    if (!start) return;
    const a = gesture(event.clientX - start[0], event.clientY - start[1]);
    start = null;
    if (a) answer(a);
  });
  stage.addEventListener("keydown", (event) => {
    const keys: Record<string, Answer> = { ArrowRight: "factory", ArrowUp: "flare", ArrowLeft: "unsure" };
    const a = keys[event.key];
    if (a) {
      event.preventDefault();
      answer(a);
    }
  });

  const share = el("button", "button share", "Share my eye");
  share.addEventListener("click", () => {
    const score = goldScore(pack.items, answers);
    void shareCanvas(swipeShareCard(today, Object.keys(answers).length, score.right, score.judged), `agninetra-swipe-${today}.png`);
  });
  card.append(
    stage,
    caption,
    buttons,
    status,
    el("p", "muted small", "Your answers stay in this browser and are never sent anywhere. Export them under Your data to keep them."),
    howSure("low", "Candidates from our map rules, not findings."),
    share,
  );
  describe();
  show();
  return card;
}
