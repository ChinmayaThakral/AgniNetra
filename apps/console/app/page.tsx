import { ConsoleClient } from "@/components/console-client";
import { AttributionFooter } from "@/components/attribution-footer";
import { GeostationaryPanel } from "@/components/geostationary-panel";
import { Guide } from "@/components/guide";
import { ModelCard } from "@/components/metric-tables";
import { ThemeToggle } from "@/components/theme-toggle";
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
          <h1>AgniNetra research console</h1>
          <div className="sub">
            What is burning over India, and how sure we are. New here? Start with the
            first tab on the right.
          </div>
          <nav className="site-links" aria-label="AgniNetra sites">
            <a href="https://agninetra.chinmayathakral.com">AgniNetra Live, the evening fire analysis</a>
            <a href="https://github.com/ChinmayaThakral/AgniNetra">Code and data</a>
            <a href="https://github.com/ChinmayaThakral/AgniNetra/wiki">Wiki</a>
            <ThemeToggle />
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
        guide={<Guide geostationary={geostationary} manifest={manifest} metrics={metrics} sources={sources} />}
        panels={[
          { title: "Geostationary", node: <GeostationaryPanel data={geostationary} /> },
          {
            title: "Model",
            node: (
              <div className="modelgrid">
                <ModelCard manifest={manifest} metrics={metrics} />
              </div>
            ),
          },
          { title: "Credits", node: <AttributionFooter manifest={manifest} /> },
        ]}
      />
    </div>
  );
}
