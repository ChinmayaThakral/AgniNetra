import { count, fraction, percent } from "@/lib/format";
import type { Manifest, Metrics } from "@/lib/schema";

function Value({ text }: { text: string }) {
  const missing = text === "not measured";
  return <span className={missing ? "notmeasured" : undefined}>{text}</span>;
}

export function ModelCard({
  metrics,
  manifest,
}: {
  metrics: Metrics;
  manifest: Manifest;
}) {
  const groups = Object.keys(metrics.perGroup);
  return (
    <>
      <div className="card">
        <h3>Baseline B1, held out groups</h3>
        <table>
          <thead>
            <tr>
              <th>Group</th>
              <th>flare F1</th>
              <th>industrial F1</th>
              <th>agri F1</th>
              <th>macro F1</th>
            </tr>
          </thead>
          <tbody>
            {groups.map((group) => {
              const row = metrics.perGroup[group];
              if (!row) return null;
              return (
                <tr key={group}>
                  <td>{group.replace("group_", "")}</td>
                  <td>{fraction(row.classes["flare"]?.f1 ?? null)}</td>
                  <td>{fraction(row.classes["industrial"]?.f1 ?? null)}</td>
                  <td>{fraction(row.classes["agricultural"]?.f1 ?? null)}</td>
                  <td>{fraction(row.macroF1)}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
        <p style={{ fontSize: "0.75rem", color: "var(--muted)", marginTop: "0.5rem" }}>
          {metrics.resampling}. Flare holds about 1.16 percent of rows, so its recall
          is low and that is the reported result rather than a defect. Feature set
          excludes the reference distances that define the weak label: including them
          gives macro F1 {fraction(metrics.leakageMacroF1, 4)} against{" "}
          {fraction(metrics.cleanMacroF1, 4)}, which is arithmetic rather than
          attribution.
        </p>
      </div>

      <div className="card">
        <h3>Calibrated uncertainty</h3>
        <table>
          <thead>
            <tr>
              <th>Group</th>
              <th>coverage</th>
              <th>nominal</th>
              <th>outside AoA</th>
            </tr>
          </thead>
          <tbody>
            {Object.entries(metrics.uncertainty).map(([group, row]) => (
              <tr key={group}>
                <td>{group.replace("group_", "")}</td>
                <td style={{ color: row.coverage < row.nominal ? "#b00020" : undefined }}>
                  {fraction(row.coverage, 4)}
                </td>
                <td>{fraction(row.nominal, 2)}</td>
                <td>{percent(row.outside_aoa_fraction)}</td>
              </tr>
            ))}
          </tbody>
        </table>
        <p style={{ fontSize: "0.75rem", color: "var(--muted)", marginTop: "0.5rem" }}>
          Split conformal assumes exchangeability between calibration and test. A
          spatially blocked split breaks it by construction, and two of three groups
          undercover. The nominal level is not achieved and is shown beside the
          measured one rather than in place of it.
        </p>
      </div>

      <div className="card">
        <h3>Baseline B2, density clustering</h3>
        <div className="row">
          <span className="k">industrial precision</span>
          <span className="v">{fraction(metrics.b2Industrial.precision)}</span>
        </div>
        <div className="row">
          <span className="k">industrial recall</span>
          <span className="v">{fraction(metrics.b2Industrial.recall)}</span>
        </div>
        <div className="row">
          <span className="k">industrial F1</span>
          <span className="v">{fraction(metrics.b2Industrial.f1)}</span>
        </div>
      </div>

      <div className="card">
        <h3>Not measured</h3>
        {Object.entries(metrics.notMeasured).map(([name, reason]) => (
          <div className="row" key={name}>
            <span className="k">{name}</span>
            <span className="v">
              <Value text="not measured" />
            </span>
          </div>
        ))}
        <ul style={{ fontSize: "0.74rem", color: "var(--muted)", paddingLeft: "1rem" }}>
          {Object.entries(metrics.notMeasured).map(([name, reason]) => (
            <li key={name}>
              <strong>{name}</strong>: {reason}
            </li>
          ))}
        </ul>
        <p style={{ fontSize: "0.74rem", color: "var(--muted)" }}>
          Wildfire: {metrics.wildfire}
        </p>
      </div>

      <div className="card">
        <h3>Provenance</h3>
        <div className="row">
          <span className="k">detections in store</span>
          <span className="v">{count(manifest.totalDetectionsInStore)}</span>
        </div>
        <div className="row">
          <span className="k">inside an Indian state</span>
          <span className="v">{count(manifest.indiaAssignedDetections)}</span>
        </div>
        <div className="row">
          <span className="k">shown here</span>
          <span className="v">{count(manifest.sampledDetections)}</span>
        </div>
        <p style={{ fontSize: "0.74rem", color: "var(--muted)", marginTop: "0.4rem" }}>
          {manifest.samplingRule}
        </p>
        <ul style={{ fontSize: "0.74rem", color: "var(--muted)", paddingLeft: "1rem" }}>
          {Object.entries(manifest.snapshots).map(([name, detail]) => (
            <li key={name}>
              <strong>{name}</strong>: {detail}
            </li>
          ))}
        </ul>
      </div>
    </>
  );
}
