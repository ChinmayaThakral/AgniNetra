import {
  ApiError,
  type Config,
  config,
  guess,
  label,
  type Label,
  me,
  nextClue,
  nextSpot,
  type Profile,
  type Queue,
  type RoundView,
  signedIn,
  signIn,
  type Spot,
  type SpotDetails,
  startRound,
} from "./community";
import { el, plural } from "./dom";
import { ABOUT, clueItem } from "./heatle";
import { award } from "./pet";
import { SwipeRecord } from "./records";
import { recall, remember } from "./store";
import { busyMonths, gesture, monthName, THRESHOLD_PX } from "./swipe-logic";
import type { Point } from "./upwind";

// Swipe: the community labels the hot spots no map explains. It opens in two steps. A
// player signs in with Google, so that every answer is one person's and nobody can vote
// twice, then proves their eye on qualifying Heatle rounds whose answers a registry
// confirms, dealt by the server. Qualified, they swipe through the unidentified spots with
// everything the project measured about each one beside the picture.

const STAMPS: Record<Label, string> = { industry: "Industry", "not industry": "Not industry", unsure: "Can't tell" };
const FAMILY: Record<string, string> = { viirs: "VIIRS", modis: "MODIS", insat: "INSAT-3DS" };

function message(error: unknown): string {
  if (error instanceof ApiError) return error.message;
  return "The server could not be reached. Check your connection and try again.";
}

function fact(name: string, value: string): HTMLElement {
  const row = el("div", "fact");
  row.append(el("dt", "", name), el("dd", "", value));
  return row;
}

function monthBars(byMonth: number[], observed: number[]): HTMLElement {
  const top = Math.max(1, ...byMonth.filter((_, i) => observed.includes(i + 1)));
  const chart = el("div", "month-bars");
  chart.setAttribute("role", "img");
  chart.setAttribute("aria-label", `Detections by month: ${byMonth.map((n, i) => `${monthName(i)} ${n}`).join(", ")}`);
  byMonth.forEach((n, i) => {
    const seen = observed.includes(i + 1);
    const bar = el("span", seen ? "month-bar" : "month-bar unobserved");
    bar.style.height = seen ? `${Math.max(4, Math.round((n / top) * 100))}%` : "100%";
    bar.title = seen ? `${monthName(i)}: ${n}` : `${monthName(i)}: not in the record`;
    const col = el("span", "month-col");
    col.append(bar, el("span", "month-name", monthName(i).slice(0, 1)));
    chart.append(col);
  });
  return chart;
}

export function spotFacts(d: SpotDetails, onPlace: (at: Point, label: string) => void): HTMLElement {
  const box = el("div", "spot-facts");
  const list = el("dl", "facts");
  const where = [d.subdistrict, d.state].filter(Boolean).join(", ");
  list.append(fact("Where", where || "not recorded"));
  list.append(fact("Coordinates", `${d.lat.toFixed(4)} N, ${d.lon.toFixed(4)} E`));
  if (d.first_seen && d.last_seen) list.append(fact("Seen", `${d.first_seen} to ${d.last_seen}${d.days_seen ? `, on ${plural(d.days_seen, "day")}` : ""}`));
  list.append(fact("Detections", `${d.detections}, ${Math.round(d.night_share * 100)}% at night`));
  if (d.median_frp_mw !== undefined) list.append(fact("Typical heat", `${d.median_frp_mw} MW fire radiative power`));
  list.append(fact("Hot area", `about ${(d.spread_m / 1000).toFixed(1)} km across`));
  const observed = d.observed_months ?? [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12];
  if (d.by_month) list.append(fact("Season", busyMonths(d.by_month, observed)));
  if (d.satellites?.length) list.append(fact("Seen by", d.satellites.map((s) => FAMILY[s] ?? s).join(", ")));
  box.append(list);
  if (d.by_month) {
    box.append(monthBars(d.by_month, observed));
    if (observed.length < 12) box.append(el("p", "small muted", "Hatched months are not in the record, which covers the burning seasons, not whole years."));
  }
  if (d.nearby.length) {
    box.append(el("h3", "", "Nearest mapped features"));
    const near = el("ul", "nearby");
    for (const n of d.nearby) near.append(el("li", "small", `${n.what}${n.name ? `, ${n.name}` : ""}: ${n.km} km away (${n.source})`));
    box.append(near);
  } else {
    box.append(el("p", "small muted", "No mapped industry, power plant or flare within 25 km."));
  }
  const links = el("div", "choices");
  const show = el("button", "button", "Show on the map");
  show.type = "button";
  show.addEventListener("click", () => onPlace([d.lon, d.lat], "This spot"));
  const osm = el("a", "button", "Open in OpenStreetMap");
  osm.href = `https://www.openstreetmap.org/?mlat=${d.lat}&mlon=${d.lon}#map=14/${d.lat}/${d.lon}`;
  osm.target = "_blank";
  osm.rel = "noopener noreferrer";
  links.append(show, osm);
  box.append(links);
  return box;
}

// Switches the games panel to another tab, for the links between Heatle and Swipe.
export function goToTab(name: string): void {
  window.dispatchEvent(new CustomEvent("agninetra-tab", { detail: name }));
}

// The same community flow drives two places: under Heatle, where players sign in and
// qualify, and in Swipe, where qualified players label. Each refreshes when the other
// changes something.
export function swipeCard(onPlace: (at: Point, label: string) => void, mode: "label" | "qualify" = "label"): HTMLElement {
  const card = el("section", mode === "label" ? "card swipe" : "card swipe qualify-card");
  let settings: Config | null = null;
  const qualifyHere = mode === "qualify";

  const intro = (): HTMLElement[] =>
    qualifyHere
      ? [el("h2", "", "Unlock Swipe"), el("p", "muted small", "Swipe asks you to name hot spots no map explains. Prove your eye here first, on sites a registry confirms.")]
      : [
          el("h2", "", "Swipe: label the unknown hot spots"),
          el("p", "muted small", "These places burn again and again, yet no map we use explains them. Your eye can help name them."),
        ];

  const toHeatle = (text: string, primary = true): HTMLButtonElement => {
    const button = el("button", primary ? "button primary" : "button", text);
    button.addEventListener("click", () => goToTab("Heatle"));
    return button;
  };

  const closed = (): void => {
    if (qualifyHere) {
      card.hidden = true;
      return;
    }
    card.replaceChildren(...intro(), el("p", "small", "Community labelling is not switched on for this server yet. Practise in Heatle meanwhile: it is the same skill."));
  };

  const signedOut = (cfg: Config): void => {
    const go = el("button", "button primary", "Sign in with Google");
    go.addEventListener("click", () => signIn(cfg.client_id));
    const steps = el("ol", "steps");
    steps.append(
      el("li", "", "Sign in with Google, so each answer is one person's."),
      el("li", "", `Qualify: solve ${cfg.qualify_needed} Heatle rounds on registry checked sites, each within ${cfg.max_clues} clues.`),
      el("li", "", "Swipe through the unknown spots: right for industry, left for not industry, up if you cannot tell."),
    );
    const actions = el("div", "choices");
    actions.append(go);
    if (!qualifyHere) actions.append(toHeatle("Practise in Heatle", false));
    card.replaceChildren(...intro(), steps, actions, el("p", "muted small", "Only your email address and your answers are kept. You can delete them at any time under Your data."));
  };

  const progress = (p: Profile, cfg: Config): HTMLElement => {
    const box = el("div", "qualify-progress");
    const bar = el("progress", "pet-bar");
    bar.max = cfg.qualify_needed;
    bar.value = Math.min(p.correct, cfg.qualify_needed);
    box.append(el("p", "small", `Qualifying: ${p.correct} of ${cfg.qualify_needed} solved within ${cfg.max_clues} clues. ${plural(p.rounds_left, "site")} left to play.`), bar);
    return box;
  };

  const qualifying = (p: Profile, cfg: Config): void => {
    if (!qualifyHere) {
      card.replaceChildren(
        ...intro(),
        progress(p, cfg),
        el("p", "small", `Swipe opens once you have solved ${cfg.qualify_needed} qualifying rounds in Heatle, each within ${cfg.max_clues} clues.`),
        toHeatle("Continue in Heatle"),
      );
      return;
    }
    const play = el("button", "button primary", "Play a qualifying round");
    play.addEventListener("click", () => void round(cfg));
    card.replaceChildren(
      ...intro(),
      progress(p, cfg),
      el("p", "small", `Each round is a site whose type a registry confirms. Solve it within ${cfg.max_clues} clues for it to count. A wrong guess opens the next clue.`),
      p.rounds_left > 0 ? play : el("p", "small", "You have played every qualifying site."),
    );
  };

  const round = async (cfg: Config): Promise<void> => {
    let view: RoundView;
    try {
      view = await startRound();
    } catch (error) {
      card.append(el("p", "small error", message(error)));
      return;
    }
    const clues = el("ol", "clues");
    const counter = el("p", "small muted", "");
    const feedback = el("p", "heatle-feedback", "");
    const choices = el("div", "choices");
    const more = el("button", "button", "Next clue");
    const after = el("div", "choices");
    const paint = (v: RoundView): void => {
      for (const clue of v.clues.slice(clues.children.length)) clues.append(clueItem(clue));
      counter.textContent = `Clue ${v.clues.length} of ${v.total_clues}. ${v.clues.length <= cfg.max_clues ? `Solve now and it counts.` : "Past the limit: this round no longer counts, but you can still learn the answer."}`;
      more.disabled = v.clues.length >= v.total_clues;
    };
    more.addEventListener("click", () => {
      more.disabled = true;
      nextClue(view.round)
        .then((v) => {
          view = v;
          paint(v);
        })
        .catch((error: unknown) => (feedback.textContent = message(error)));
    });
    for (const choice of view.choices) {
      const button = el("button", "choice", choice);
      button.addEventListener("click", () => {
        for (const b of choices.querySelectorAll("button")) b.disabled = true;
        guess(view.round, choice)
          .then((reply) => {
            if ("counted" in reply) {
              const used = view.clues.length;
              paint({ ...view, clues: reply.clues, total_clues: reply.clues.length });
              counter.textContent = `Round over after ${plural(used, "clue")}. Every clue is shown below so you can learn from it.`;
              more.disabled = true;
              button.classList.add(reply.right ? "right" : "wrong");
              feedback.className = reply.right ? "heatle-feedback right" : "heatle-feedback";
              feedback.textContent = `${reply.right ? (reply.counted ? "Right, and it counts." : "Right, but past the clue limit, so it does not count.") : "Not this time."} It is a ${reply.answer}. ${ABOUT[reply.answer] ?? ""}`;
              if (reply.right) award(reply.counted ? "heatleSolved" : "heatlePlayed");
              window.dispatchEvent(new Event("agninetra-data"));
              window.dispatchEvent(new Event("agninetra-community"));
              const next = el("button", "button primary", reply.qualified ? "Start labelling in Swipe" : "Next round");
              next.addEventListener("click", () => (reply.qualified ? goToTab("Swipe") : void round(cfg)));
              after.replaceChildren(next, el("span", "small muted", `${reply.correct} of ${cfg.qualify_needed} counted.`));
              return;
            }
            view = reply;
            button.classList.add("wrong");
            feedback.className = "heatle-feedback";
            feedback.textContent = `Not a ${choice}. ${ABOUT[choice] ?? ""} Here is another clue.`;
            paint(reply);
            for (const b of choices.querySelectorAll("button")) if (!b.classList.contains("wrong")) b.disabled = false;
          })
          .catch((error: unknown) => {
            feedback.textContent = message(error);
            for (const b of choices.querySelectorAll("button")) if (!b.classList.contains("wrong")) b.disabled = false;
          });
      });
      choices.append(button);
    }
    card.replaceChildren(el("h2", "", "Qualifying round"), counter, clues, more, choices, feedback, after);
    paint(view);
  };

  const labelling = (queue: Queue): void => {
    const spot = queue.item;
    const status = el("p", "small muted", `You have labelled ${queue.answered} of ${queue.total} spots.`);
    if (!spot) {
      card.replaceChildren(el("h2", "", "Swipe"), el("p", "", "You have labelled every spot. Thank you: each answer helps find the heat sources the maps are missing."), status);
      return;
    }
    const kinds = queue.kinds ?? [];
    const stage = el("div", "swipe-stage");
    const sheet = el("div", "swipe-card");
    sheet.tabIndex = 0;
    sheet.setAttribute("aria-label", "Picture to label. Drag right for industry, left for not industry, up if you cannot tell, or use the arrow keys.");
    const picture = el("img", "chip");
    picture.width = 256;
    picture.height = 256;
    picture.draggable = false;
    let wide = false;
    const paintPicture = (): void => {
      picture.src = wide && spot.wide ? spot.wide : spot.chip;
      picture.alt = `Satellite picture of an unidentified hot spot, ${wide ? "10" : "2.6"} km across, seen ${spot.acquired}`;
    };
    paintPicture();
    const stamp = el("span", "stamp", "");
    sheet.append(picture, stamp);
    stage.append(sheet);
    const zoom = el("button", "button", "Zoom out");
    zoom.type = "button";
    zoom.hidden = !spot.wide;
    zoom.addEventListener("click", () => {
      wide = !wide;
      zoom.textContent = wide ? "Zoom in" : "Zoom out";
      paintPicture();
    });
    const caption = el("p", "muted small", `Sentinel-2, ${spot.acquired}. Contains modified Copernicus Sentinel data.`);
    const feedback = el("p", "small", "");
    const buttons = el("div", "choices swipe-choices");
    let busy = false;

    const send = (answer: Label, kind?: string): void => {
      label(spot.id, answer, kind)
        .then((next) => {
          const mine = recall("swipe", (v) => SwipeRecord.parse(v), {});
          remember("swipe", { ...mine, [spot.id]: { a: answer, at: new Date().toISOString() } });
          window.dispatchEvent(new Event("agninetra-data"));
          award("swipe");
          labelling(next);
        })
        .catch((error: unknown) => {
          busy = false;
          sheet.style.transform = "";
          feedback.textContent = message(error);
        });
    };

    const askKind = (): void => {
      const pick = el("div", "kind-pick");
      pick.append(el("p", "small", "What kind of industry, if you can tell?"));
      const row = el("div", "choices");
      for (const kind of kinds) {
        const b = el("button", "choice", kind);
        b.addEventListener("click", () => send("industry", kind));
        row.append(b);
      }
      const skip = el("button", "choice", "Not sure which");
      skip.addEventListener("click", () => send("industry"));
      row.append(skip);
      pick.append(row);
      buttons.replaceWith(pick);
      pick.querySelector("button")?.focus();
    };

    const commit = (answer: Label): void => {
      if (busy) return;
      busy = true;
      const fly: Record<Label, string> = { industry: "translate(140%, 0) rotate(18deg)", "not industry": "translate(-140%, 0) rotate(-18deg)", unsure: "translate(0, -140%)" };
      sheet.style.transition = "transform 220ms ease-in";
      sheet.style.transform = fly[answer];
      window.setTimeout(() => {
        if (answer === "industry" && kinds.length) askKind();
        else send(answer);
      }, 220);
    };

    let start: [number, number] | null = null;
    sheet.addEventListener("pointerdown", (event) => {
      if (busy) return;
      start = [event.clientX, event.clientY];
      sheet.setPointerCapture(event.pointerId);
      sheet.style.transition = "none";
    });
    sheet.addEventListener("pointermove", (event) => {
      if (!start) return;
      const dx = event.clientX - start[0];
      const dy = event.clientY - start[1];
      sheet.style.transform = `translate(${dx}px, ${Math.min(dy, 40)}px) rotate(${dx / 18}deg)`;
      const would = gesture(dx, dy, THRESHOLD_PX / 2);
      stamp.textContent = would ? STAMPS[would] : "";
      stamp.className = would ? `stamp show ${would === "not industry" ? "no" : would}` : "stamp";
    });
    const release = (event: PointerEvent): void => {
      if (!start) return;
      const answer = gesture(event.clientX - start[0], event.clientY - start[1]);
      start = null;
      if (answer) commit(answer);
      else {
        sheet.style.transition = "transform 180ms ease-out";
        sheet.style.transform = "";
        stamp.className = "stamp";
      }
    };
    sheet.addEventListener("pointerup", release);
    sheet.addEventListener("pointercancel", release);
    sheet.addEventListener("keydown", (event) => {
      const keys: Record<string, Label> = { ArrowRight: "industry", ArrowLeft: "not industry", ArrowUp: "unsure" };
      const answer = keys[event.key];
      if (answer) {
        event.preventDefault();
        commit(answer);
      }
    });
    const options: [Label, string][] = [
      ["not industry", "Not industry"],
      ["unsure", "Can't tell"],
      ["industry", "Industry"],
    ];
    for (const [answer, text] of options) {
      const b = el("button", `choice swipe-${answer === "not industry" ? "no" : answer}`, text);
      b.addEventListener("click", () => commit(answer));
      buttons.append(b);
    }
    const facts = spot.details ? spotFacts(spot.details, onPlace) : el("p", "small muted", "No details recorded for this spot.");
    card.replaceChildren(
      el("h2", "", "Swipe: what is this hot spot?"),
      el("p", "muted small", "Drag the picture right for industry, left for not industry (a farm or forest fire, a town), up if you cannot tell."),
      stage,
      buttons,
      zoom,
      caption,
      feedback,
      facts,
      status,
    );
    sheet.focus({ preventScroll: true });
    if (spot.wide) new Image().src = spot.wide;
  };

  const open = async (): Promise<void> => {
    card.replaceChildren(...intro(), el("p", "small muted", "Loading."));
    settings ??= await config();
    if (!settings) return closed();
    if (!signedIn()) return signedOut(settings);
    try {
      const profile = await me();
      if (!profile.qualified) return qualifying(profile, settings);
      if (qualifyHere) {
        const go = el("button", "button primary", "Label spots in Swipe");
        go.addEventListener("click", () => goToTab("Swipe"));
        card.replaceChildren(el("h2", "", "Swipe is unlocked"), el("p", "small", `You qualified with ${profile.correct} rounds solved. Thank you for lending your eye.`), go);
        return;
      }
      labelling(await nextSpot());
    } catch (error) {
      if (error instanceof ApiError && error.status === 401) return signedOut(settings);
      card.replaceChildren(...intro(), el("p", "small error", message(error)));
    }
  };

  // A finished qualifying round changes what the other card should show.
  window.addEventListener("agninetra-community", () => {
    if (card.querySelector(".clues") === null) void open();
  });
  void open();
  return card;
}

export type { Spot };
