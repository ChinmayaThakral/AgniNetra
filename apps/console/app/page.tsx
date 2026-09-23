import { ConsoleClient } from "@/components/console-client";
import { AttributionFooter } from "@/components/attribution-footer";
import { GeostationaryPanel } from "@/components/geostationary-panel";
import { ModelCard } from "@/components/metric-tables";
import {
  loadDetections,
  loadGeostationary,
  loadManifest,
  loadMetrics,
  loadSources,
} from "@/lib/data";

export const dynamic = "force-static";

/**
 * Server component. Reads the exported artifacts, parses them through zod, and
 * hands plain data to the one client component that needs interaction.
 */
export default async function Page() {
  const [detections, sources, metrics, manifest, geostationary] = await Promise.all([
    loadDetections(),
    loadSources(),
    loadMetrics(),
    loadManifest(),
    loadGeostationary(),
  ]);

  return (
    <div className="shell">
      <header className="masthead">
        <div>
          <h1>AgniNetra console</h1>
          <div className="sub">
            Thermal source attribution over India. Displays precomputed phase 4
            results, the phase 5 geostationary window, and runs no model.
          </div>
        </div>
        <div className="sub" style={{ textAlign: "right" }}>
          Detections: held out group <strong>{manifest.heldOutGroup}</strong>,{" "}
          {manifest.heldOutStates.join(", ")}
          <br />
          Persistent sources: all of India, whole record
          <br />
          Windows: {manifest.windows.join(" | ")}
        </div>
      </header>

      <ConsoleClient
        detections={detections}
        manifest={manifest}
        sources={sources}
        heldOutCoverage={metrics.uncertainty[manifest.heldOutGroup]?.coverage ?? null}
      />

      <div style={{ borderTop: "1px solid var(--line)", padding: "1rem" }}>
        <h2>Phase 5, what the geostationary record adds</h2>
        <div style={{ marginTop: "0.6rem" }}>
          <GeostationaryPanel data={geostationary} />
        </div>
      </div>

      <div style={{ borderTop: "1px solid var(--line)", padding: "1rem" }}>
        <h2>Model card</h2>
        <div
          style={{
            display: "grid",
            gridTemplateColumns: "repeat(auto-fit, minmax(19rem, 1fr))",
            gap: "0.8rem",
            marginTop: "0.6rem",
          }}
        >
          <ModelCard manifest={manifest} metrics={metrics} />
        </div>
      </div>

      <AttributionFooter manifest={manifest} />
    </div>
  );
}
