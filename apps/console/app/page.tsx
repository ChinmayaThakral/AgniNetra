import { ConsoleClient } from "@/components/console-client";
import { AttributionFooter } from "@/components/attribution-footer";
import { ModelCard } from "@/components/metric-tables";
import { loadDetections, loadManifest, loadMetrics, loadSources } from "@/lib/data";

export const dynamic = "force-static";

/**
 * Server component. Reads the exported artifacts, parses them through zod, and
 * hands plain data to the one client component that needs interaction.
 */
export default async function Page() {
  const [detections, sources, metrics, manifest] = await Promise.all([
    loadDetections(),
    loadSources(),
    loadMetrics(),
    loadManifest(),
  ]);

  return (
    <div className="shell">
      <header className="masthead">
        <div>
          <h1>AgniNetra console</h1>
          <div className="sub">
            Thermal source attribution over India. Displays precomputed phase 4
            results and runs no model.
          </div>
        </div>
        <div className="sub" style={{ textAlign: "right" }}>
          Held out group <strong>{manifest.heldOutGroup}</strong>:{" "}
          {manifest.heldOutStates.join(", ")}
          <br />
          Windows: {manifest.windows.join(" | ")}
        </div>
      </header>

      <ConsoleClient
        detections={detections}
        manifest={manifest}
        sources={sources}
      />

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
