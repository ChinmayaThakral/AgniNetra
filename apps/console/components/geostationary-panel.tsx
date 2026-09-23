import type { Geostationary } from "../lib/schema";

// A server component. It renders precomputed phase 5 results and runs nothing, which
// is the same contract the rest of this console works to.
//
// Every figure below carries its units, and the ones that are weaker than they look
// say so beside themselves rather than in a footnote, because a reader who takes the
// evening share without the corroboration rate has taken half the result.

function Hours({ values }: { values: (number | null)[] }) {
  const observed = values.filter((v): v is number => v !== null);
  const peak = observed.length > 0 ? Math.max(...observed) : 0;
  return (
    <div className="hours">
      {values.map((value, hour) => {
        const height = value === null || peak === 0 ? 0 : (value / peak) * 100;
        const evening = hour >= 15 && hour < 20;
        return (
          <div className="hour" key={hour} title={`${hour}:00 IST, ${value ?? "not measured"} per granule`}>
            <div
              className={evening ? "bar evening" : "bar"}
              style={{ height: `${Math.max(height, value === null ? 0 : 1.5)}%` }}
            />
            {hour % 6 === 0 ? <span className="tick">{hour}</span> : <span className="tick" />}
          </div>
        );
      })}
    </div>
  );
}

export function GeostationaryPanel({ data }: { data: Geostationary }) {
  const change = data.detectorChange;
  return (
    <section className="card geo">
      <h3>Geostationary window, INSAT-3DS</h3>
      <p className="note">
        What a half hourly sensor sees in the hours the polar constellation never
        samples. Two three day windows, one in each residue season. Three days is a
        sample of a season, not a season.
      </p>

      {data.windows.map((w) => (
        <div className="window" key={w.key}>
          <h4>
            {w.label} <span className="span">{w.span}</span>
          </h4>
          <div className="row">
            <span className="k">granules</span>
            <span className="v">
              {w.granules} over {w.slotsPresent} of {w.slotsExpected} half hour slots,{" "}
              {w.hoursObserved} of 24 hours observed
            </span>
          </div>
          <div className="row">
            <span className="k">detections</span>
            <span className="v">
              {w.detections.toLocaleString()} ({w.detectionsInStubbleBox.toLocaleString()} in
              the Punjab and Haryana box)
            </span>
          </div>
          <div className="row">
            <span className="k">evening share, 15 to 20 IST</span>
            <span className="v strong">{w.eveningSharePct.toFixed(1)}%</span>
          </div>
          <div className="row">
            <span className="k">polar overpass hours</span>
            <span className="v">{w.polarOverpassSharePct.toFixed(1)}%</span>
          </div>

          <Hours values={w.meanByHour} />
          <p className="axis">
            mean detections per granule by hour IST, red is the window the polar record
            never samples
          </p>

          <table className="mini">
            <caption>
              By state, detections per granule normalised for unequal slot coverage
            </caption>
            <thead>
              <tr>
                <th>State</th>
                <th>Per granule</th>
                <th>Evening</th>
                <th>Peak IST</th>
              </tr>
            </thead>
            <tbody>
              {w.states.slice(0, 6).map((s) => (
                <tr key={s.name}>
                  <td>{s.name}</td>
                  <td>{s.perGranule.toFixed(1)}</td>
                  <td>{s.eveningSharePct.toFixed(1)}%</td>
                  <td>{String(s.peakHourIst).padStart(2, "0")}h</td>
                </tr>
              ))}
            </tbody>
          </table>

          <table className="mini">
            <caption>
              Corroborated against the polar record, {w.polarDetections.toLocaleString()}{" "}
              polar detections in the window
            </caption>
            <thead>
              <tr>
                <th>Radius</th>
                <th>Checkable</th>
                <th>Corroborated</th>
                <th>Rate</th>
              </tr>
            </thead>
            <tbody>
              {w.collocation.map((c) => (
                <tr key={c.radiusM}>
                  <td>{(c.radiusM / 1000).toFixed(0)} km</td>
                  <td>{c.checkable}</td>
                  <td>{c.corroborated}</td>
                  <td>{c.ratePct.toFixed(1)}%</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ))}

      <div className="window">
        <h4>Solar artifact removed</h4>
        <div className="row">
          <span className="k">detections before, after</span>
          <span className="v">
            {change.before.toLocaleString()} to {change.after.toLocaleString()}
          </span>
        </div>
        <div className="row">
          <span className="k">Punjab and Haryana box</span>
          <span className="v">
            {change.stubbleBoxBefore.toLocaleString()} to{" "}
            {change.stubbleBoxAfter.toLocaleString()}
          </span>
        </div>
        <p className="note">{change.rule}</p>
      </div>

      <div className="window">
        <h4>Read these with</h4>
        <ul className="caveats">
          {data.caveats.map((c) => (
            <li key={c}>{c}</li>
          ))}
        </ul>
      </div>
    </section>
  );
}
