"use client";

import { classColour, days, fraction, metres, percent, power } from "@/lib/format";
import type { Detection } from "@/lib/schema";

/**
 * The evidence panel is the demonstration. A reviewer clicking one detection should
 * see why the call was made, how confident it is, and whether the location is inside
 * the applicability domain. A probability shown without its prediction set would
 * misrepresent what the system knows.
 */
export function EvidencePanel({
  detection,
  nominal,
  heldOutGroup,
  heldOutCoverage,
}: {
  detection: Detection | null;
  nominal: number;
  heldOutGroup: string;
  heldOutCoverage: number | null;
}) {
  if (!detection) {
    return (
      <div className="card">
        <h3>Detection evidence</h3>
        <p style={{ color: "var(--muted)" }}>
          Select a detection on the map to see its posterior, its conformal
          prediction set, its applicability status and its recurrence history.
        </p>
      </div>
    );
  }

  const entries = Object.entries(detection.posterior).sort((a, b) => b[1] - a[1]);
  const abstains = detection.predictionSet.length !== 1;

  return (
    <div className="card">
      <h3>Detection evidence</h3>
      <div className="row">
        <span className="k">identifier</span>
        <span className="v">
          <code>{detection.id}</code>
        </span>
      </div>
      <div className="row">
        <span className="k">acquired, IST</span>
        <span className="v">
          {detection.date} {detection.isNight ? "night" : "day"}
        </span>
      </div>
      <div className="row">
        <span className="k">location</span>
        <span className="v">
          {detection.lat.toFixed(4)} degrees N, {detection.lon.toFixed(4)} degrees E
        </span>
      </div>
      <div className="row">
        <span className="k">state</span>
        <span className="v">{detection.state ?? "outside every Indian state"}</span>
      </div>
      <div className="row">
        <span className="k">radiative power</span>
        <span className={detection.frpMw === null ? "v notmeasured" : "v"}>
          {power(detection.frpMw)}
        </span>
      </div>

      <h3 style={{ marginTop: "0.8rem" }}>Class posterior</h3>
      {entries.map(([name, value]) => (
        <div key={name} style={{ marginBottom: "0.35rem" }}>
          <div className="row" style={{ padding: 0 }}>
            <span className="k">{name}</span>
            <span className="v">{fraction(value, 4)}</span>
          </div>
          <div className="bar">
            <span style={{ width: `${value * 100}%`, background: classColour(name) }} />
          </div>
        </div>
      ))}

      <h3 style={{ marginTop: "0.8rem" }}>What the system will commit to</h3>
      <div className="row">
        <span className="k">prediction set, {Math.round(nominal * 100)} percent nominal</span>
        <span className="v">
          {detection.predictionSet.length === 0 ? (
            <span className="notmeasured">empty, abstains</span>
          ) : (
            detection.predictionSet.map((name) => (
              <span
                className="chip"
                key={name}
                style={{ background: classColour(name), marginLeft: "0.2rem" }}
              >
                {name}
              </span>
            ))
          )}
        </span>
      </div>
      <div className="row">
        <span className="k">applicability domain</span>
        <span className="v">
          {detection.outsideApplicability === null ? (
            <span>not assessable, a feature is unobserved</span>
          ) : detection.outsideApplicability ? (
            <span style={{ color: "#b00020" }}>outside, treat with caution</span>
          ) : (
            "inside"
          )}
        </span>
      </div>
      {abstains ? (
        <p style={{ fontSize: "0.74rem", color: "var(--muted)" }}>
          The set is not a single class, so the system is declining to commit at this
          level.{" "}
          {heldOutCoverage === null
            ? `Coverage on ${heldOutGroup} is not measured.`
            : `Measured coverage on ${heldOutGroup} is ${heldOutCoverage.toFixed(4)} against a nominal ${nominal.toFixed(2)}, ${heldOutCoverage < nominal ? "below" : "at or above"} it.`}
        </p>
      ) : null}

      <h3 style={{ marginTop: "0.8rem" }}>Recurrence at this location</h3>
      <div className="row">
        <span className="k">prior detections, 90 days</span>
        <span className="v">{detection.priorCount90d}</span>
      </div>
      <div className="row">
        <span className="k">prior detections, 30 days</span>
        <span className="v">{detection.priorCount30d}</span>
      </div>
      <div className="row">
        <span className="k">night fraction, 90 days</span>
        <span className={detection.nightFraction90d === null ? "v notmeasured" : "v"}>
          {fraction(detection.nightFraction90d)}
        </span>
      </div>
      <div className="row">
        <span className="k">mean gap between detections</span>
        <span className={detection.meanGapDays === null ? "v notmeasured" : "v"}>
          {days(detection.meanGapDays)}
        </span>
      </div>

      <h3 style={{ marginTop: "0.8rem" }}>Nearest reference</h3>
      <div className="row">
        <span className="k">catalogued flare</span>
        <span className={detection.nearestFlareBand === null ? "v notmeasured" : "v"}>
          {detection.nearestFlareBand ?? "not measured"}
        </span>
      </div>
      <div className="row">
        <span className="k">OSM industrial feature</span>
        <span className={detection.nearestIndustrialM === null ? "v notmeasured" : "v"}>
          {metres(detection.nearestIndustrialM)}
        </span>
      </div>
      <div className="row">
        <span className="k">GEM asset, operating on this date</span>
        <span className={detection.nearestGemM === null ? "v notmeasured" : "v"}>
          {metres(detection.nearestGemM)}
        </span>
      </div>
      <div className="row">
        <span className="k">weak label</span>
        <span className="v">
          <span className="pill">{detection.weakLabel}</span>
        </span>
      </div>
      <p style={{ fontSize: "0.74rem", color: "var(--muted)", marginTop: "0.4rem" }}>
        The weak label is derived from these distances and the land cover class. It is
        the training target, not ground truth, and none of these distances is a model
        feature. Percentages are shares of one, not confidence intervals:{" "}
        {percent(null)} where a quantity was not computed.
      </p>
    </div>
  );
}
