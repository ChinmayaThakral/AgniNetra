import { el, plural } from "./dom";
import { type Mood, netuSvg } from "./netu";
import { itemsAt, LEVELS, levelOf, nextLevelXp, petState } from "./pet";
import { petShareCard, shareCanvas } from "./share-card";

// Your Netu: its level, what it wears, and how it grows. Redrawn whenever play earns it
// experience, from this phone's own record only.

export function petCard(mood: () => Mood): HTMLElement {
  const card = el("section", "card pet");
  const render = (): void => {
    const { xp } = petState();
    const level = levelOf(xp);
    const wearing = itemsAt(level);
    const next = nextLevelXp(xp);
    const floor = LEVELS[level - 1]?.xp ?? 0;
    const body = el("div", "pet-body");
    body.append(netuSvg(mood(), 120, wearing));
    const facts = el("div", "pet-facts");
    facts.append(el("p", "big", `Level ${level}`));
    const bar = el("progress", "pet-bar");
    bar.max = next === null ? 1 : next - floor;
    bar.value = next === null ? 1 : xp - floor;
    facts.append(bar, el("p", "small", next === null ? `${plural(xp, "point")}. Top level reached.` : `${plural(xp, "point")}, ${next - xp} to level ${level + 1}`));
    facts.append(el("p", "small", wearing.length ? `Wearing: ${wearing.join(", ")}` : "Nothing to wear yet. Play to earn a cricket cap."));
    body.append(facts);
    const share = el("button", "button share", "Share my Netu");
    share.addEventListener("click", () => {
      void petShareCard(mood(), level, xp, wearing).then((canvas) => shareCanvas(canvas, `my-netu-level-${level}.png`));
    });
    card.replaceChildren(
      el("h2", "", "Your Netu"),
      body,
      el("p", "muted small", "Netu grows when you look, never when anything burns: a Swipe picture is 1 point, a checked site called right 2, a Heatle played 1 and solved 5. Its mood follows your city's air."),
      share,
    );
  };
  window.addEventListener("netu-xp", render);
  render();
  return card;
}
