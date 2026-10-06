import { count, fraction } from "@/lib/format";
import type { Geostationary, Manifest, Metrics, Source } from "@/lib/schema";

// The first thing a visitor reads: what the console is, how to read the map, and what the
// project found, in plain words. Every number is read from the same exported files the
// other tabs show, so this page cannot drift from them.

export function Guide({
  manifest,
  metrics,
  sources,
  geostationary,
}: {
  manifest: Manifest;
  metrics: Metrics;
  sources: Source[];
  geostationary: Geostationary;
}) {
  const unregistered = sources.filter((s) => !s.registered).length;
  const held = metrics.uncertainty[manifest.heldOutGroup];
  const groups = Object.values(metrics.perGroup).map((g) => g.macroF1);
  const kharif = geostationary.windows[0];
  return (
    <div className="guide">
      <section className="card">
        <h3>What this is</h3>
        <p>
          Satellites record every hot spot over India, but not what is burning. A crop fire, a steel furnace and a
          gas flare look the same in the data. This console shows a model that guesses the source of each hot spot,
          how sure it is, and where it is unsure. It shows results computed in advance; nothing is recomputed here.
        </p>
      </section>

      <section className="card">
        <h3>How to read the map</h3>
        <ul className="plain">
          <li>
            <strong>Dots</strong> are single satellite detections in the held out states ({manifest.heldOutStates.join(", ")}),
            the states the model never saw while learning. Colour is the model&apos;s guess: red flare, orange industry, green farm burning.
          </li>
          <li>
            <strong>A black outline</strong> means the model would not commit to one answer: its honest set of possible answers has more than one.
          </li>
          <li>
            <strong>Rings</strong> are places that burn again and again, found across all of India. A <strong>red ring</strong> is one that no
            map or registry we use explains.
          </li>
          <li>Click a dot to see its evidence. Use the bar at the bottom to filter by class or by date.</li>
        </ul>
      </section>

      <section className="card">
        <h3>What we found</h3>
        <ul className="plain">
          <li>
            <strong>{count(sources.length)} places in India burn again and again</strong>, and {count(unregistered)} of them match no registry
            of plants, mines or flares we checked. See the Sources tab.
          </li>
          {groups.length ? (
            <li>
              On regions it never saw, the model&apos;s balanced score (macro F1) ranged from {fraction(Math.min(...groups), 2)} to{" "}
              {fraction(Math.max(...groups), 2)}, where 1 would be perfect. Flares are rare, so they are the hardest.
            </li>
          ) : null}
          {held ? (
            <li>
              When the model gives a set of answers it aims to include the right one {Math.round(held.nominal * 100)}% of the time; on the held
              out states it did {Math.round(held.coverage * 100)}%. The gap is reported, not hidden.
            </li>
          ) : null}
          {kharif ? (
            <li>
              India&apos;s own INSAT-3DS satellite, looking every 30 minutes, saw {Math.round(kharif.eveningSharePct)}% of its{" "}
              {kharif.label.toLowerCase()} detections in the evening hours that the polar satellites never visit. See the Geostationary tab.
            </li>
          ) : null}
        </ul>
      </section>

      <section className="card">
        <h3>Words used here</h3>
        <dl className="glossary">
          <dt>Detection</dt>
          <dd>One hot pixel a satellite saw, with a place, a time and its heat.</dd>
          <dt>FRP</dt>
          <dd>Fire radiative power, in megawatts: how much heat the fire gives off.</dd>
          <dt>Weak label</dt>
          <dd>A training answer taken from maps (near a known flare, plant or field), not checked on the ground.</dd>
          <dt>Held out</dt>
          <dd>States kept away from the model while it learned, so its score is a fair test.</dd>
          <dt>Prediction set</dt>
          <dd>The answers the model cannot rule out at its chosen confidence. One answer means it is sure enough.</dd>
          <dt>Applicability</dt>
          <dd>Whether a detection looks like what the model learned from. Outside it, treat the guess with extra care.</dd>
          <dt>Persistent source</dt>
          <dd>A place with many detections over the record, grouped within 500 m.</dd>
        </dl>
      </section>
    </div>
  );
}
