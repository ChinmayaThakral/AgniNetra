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
          <nav className="site-links" aria-label="AgniNetra sites">
            <a href="https://agninetra.chinmayathakral.com">AgniNetra Live, the evening fire match</a>
            <a href="https://github.com/ChinmayaThakral/AgniNetra">Code and data</a>
          </nav>
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
        panels={[
          { title: "Phase 5: what the geostationary record adds", node: <GeostationaryPanel data={geostationary} /> },
          {
            title: "Model card",
            node: (
              <div className="modelgrid">
                <ModelCard manifest={manifest} metrics={metrics} />
              </div>
            ),
            startOpen: false,
          },
          { title: "Sources and credits", node: <AttributionFooter manifest={manifest} />, startOpen: false },
        ]}
      />
    </div>
  );
}
