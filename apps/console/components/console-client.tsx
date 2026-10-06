"use client";

import * as maplibregl from "maplibre-gl";
import type { StyleSpecification } from "maplibre-gl";
import "maplibre-gl/dist/maplibre-gl.css";
import { useEffect, useMemo, useRef, useState, useSyncExternalStore } from "react";

maplibregl.setWorkerUrl("/maplibre/maplibre-gl-worker.mjs");

import { classColour, count, metres } from "@/lib/format";
import type { Detection, Manifest, Source } from "@/lib/schema";
import { EvidencePanel } from "./evidence-panel";

const CLASSES = ["flare", "industrial", "agricultural"] as const;

/**
 * Basemap without an API key, so the console runs with no credential.
 *
 * Carto's basemaps served without a key but now stamp every tile with an
 * "API KEY REQUIRED" watermark, which is unusable in a demonstration. The
 * OpenStreetMap standard tile layer needs no key and is already attributed here
 * under ODbL, which the project uses for its industrial features anyway.
 */
// The basemap tile source is configuration, not a constant.
//
// This previously pointed at a.tile.openstreetmap.org directly. The OSM Foundation
// tile usage policy forbids distributing an application that uses those tiles
// without permission, and separately prohibits bots that pan and zoom to force
// rendering, which the screenshot script does. Both applied here. D69.
//
// Every compliant provider requires an account, which is the team's to create, so
// there is deliberately no default. With the variable unset the map renders the
// data over an empty ground and says why, because shipping a working map that
// breaches somebody's terms is worse than shipping an obviously unconfigured one.
//
// Set NEXT_PUBLIC_BASEMAP_TILES to a comma separated list of tile URL templates,
// and NEXT_PUBLIC_BASEMAP_ATTRIBUTION to the provider's required notice. The
// OpenStreetMap attribution below is kept regardless, because the underlying data
// is still ODbL whoever serves the tiles.
const OSM_NOTICE =
  '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors, ODbL 1.0';

const BASEMAP_TILES = (process.env.NEXT_PUBLIC_BASEMAP_TILES ?? "")
  .split(",")
  .map((t) => t.trim())
  .filter(Boolean);

export const BASEMAP_CONFIGURED = BASEMAP_TILES.length > 0;

const PROVIDER_NOTICE = process.env.NEXT_PUBLIC_BASEMAP_ATTRIBUTION ?? "";

const STYLE: StyleSpecification = {
  version: 8,
  sources: BASEMAP_CONFIGURED
    ? {
        basemap: {
          type: "raster",
          tiles: BASEMAP_TILES,
          tileSize: 256,
          maxzoom: 19,
          attribution: [PROVIDER_NOTICE, OSM_NOTICE].filter(Boolean).join(" | "),
        },
      }
    : {},
  layers: BASEMAP_CONFIGURED
    ? [
        {
          id: "basemap",
          type: "raster",
          source: "basemap",
          paint: { "raster-opacity": 0.72 },
        },
      ]
    : [],
};

// The export text promises the posterior. It was never written, so a reader following
// the text would look for a column that did not exist. D122.
const POSTERIOR_CLASSES = ["flare", "industrial", "agricultural"] as const;

function toCsv(rows: Detection[]): string {
  const header = [
    "id", "lon", "lat", "date", "state", "frp_mw", "is_night", "weak_label",
    "predicted", "prediction_set", "outside_applicability", "prior_count_90d",
    "night_fraction_90d", "nearest_flare_band", "nearest_industrial_m", "nearest_gem_m",
    ...POSTERIOR_CLASSES.map((c) => `posterior_${c}`),
  ];
  const lines = rows.map((d) =>
    [
      d.id, d.lon, d.lat, d.date, d.state ?? "", d.frpMw ?? "not measured",
      d.isNight, d.weakLabel, d.predicted, d.predictionSet.join(" "),
      d.outsideApplicability ?? "not assessable", d.priorCount90d,
      d.nightFraction90d ?? "not measured",
      d.nearestFlareBand ?? "not measured",
      d.nearestIndustrialM ?? "not measured",
      d.nearestGemM ?? "not measured",
      ...POSTERIOR_CLASSES.map((c) => d.posterior[c] ?? "not measured"),
    ].join(","),
  );
  return [header.join(","), ...lines].join("\n");
}

// MapLibre has needed a WebGL 2 context since version 5 and no longer ships a
// supported() helper, so the check is direct. Support cannot change while the page
// is open, so the probe runs once and the store reading it never notifies. The
// server cannot probe and assumes support; hydration corrects the message.
let webgl2: boolean | undefined;

function hasWebgl2(): boolean {
  if (webgl2 === undefined) {
    try {
      webgl2 = document.createElement("canvas").getContext("webgl2") !== null;
    } catch {
      webgl2 = false;
    }
  }
  return webgl2;
}

const neverChanges = () => () => {};

const NO_WEBGL2 =
  "This browser could not create a WebGL context, which MapLibre requires. " +
  "Every panel below still works; only the map is unavailable.";

export function ConsoleClient({
  detections,
  sources,
  manifest,
  heldOutCoverage,
}: {
  detections: Detection[];
  sources: Source[];
  manifest: Manifest;
  heldOutCoverage: number | null;
}) {
  const container = useRef<HTMLDivElement | null>(null);
  const map = useRef<maplibregl.Map | null>(null);
  const [mapError, setMapError] = useState<string | null>(null);
  const [selected, setSelected] = useState<Detection | null>(null);
  const [active, setActive] = useState<Set<string>>(new Set(CLASSES));
  const [abstainOnly, setAbstainOnly] = useState(false);
  const [dayIndex, setDayIndex] = useState<number>(-1);
  // Read during render, not set from the effect, which cost a second render.
  const webgl2Available = useSyncExternalStore(neverChanges, hasWebgl2, () => true);
  const shownError = webgl2Available ? mapError : NO_WEBGL2;

  const dates = useMemo(
    () => Array.from(new Set(detections.map((d) => d.date))).sort(),
    [detections],
  );

  const visible = useMemo(() => {
    return detections.filter((d) => {
      if (!active.has(d.predicted)) return false;
      if (abstainOnly && d.predictionSet.length === 1) return false;
      if (dayIndex >= 0 && d.date !== dates[dayIndex]) return false;
      return true;
    });
  }, [detections, active, abstainOnly, dayIndex, dates]);

  useEffect(() => {
    const node = container.current;
    // Checked before construction so an unsupported browser gets a sentence
    // rather than a blank rectangle.
    if (!node || map.current || !hasWebgl2()) return;

    let instance: maplibregl.Map;
    try {
      instance = new maplibregl.Map({
        container: node,
        style: STYLE,
        // The India bounding box the detections were requested for. Fitting to it
        // rather than setting a centre and zoom keeps the frame on India at any
        // container size; a fixed zoom opened on Kazakhstan to Indonesia.
        bounds: [
          [68.0, 6.5],
          [97.5, 37.5],
        ],
        fitBoundsOptions: { padding: 24 },
        // Panning and zooming stay around India, the only place the data covers.
        maxBounds: [
          [55.0, -2.0],
          [110.0, 45.0],
        ],
        renderWorldCopies: false,
      });
    } catch (error) {
      // Without this the throw propagates out of the effect and React unmounts
      // the whole subtree, taking the panels with it. Measured: a headless run
      // with no GPU lost .mapwrap and .aside together. A failed construction is
      // only known by attempting it, which is this effect's job, and the render
      // the rule warns about is the one that shows the message.
      // eslint-disable-next-line react-hooks/set-state-in-effect
      setMapError(
        `The map failed to initialise: ${
          error instanceof Error ? error.message : String(error)
        }`,
      );
      return;
    }

    map.current = instance;
    instance.addControl(new maplibregl.NavigationControl({}), "top-right");
    instance.addControl(new maplibregl.ScaleControl({ unit: "metric" }));
    instance.on("error", (event) => {
      const message = event.error?.message ?? "unknown map error";
      if (message.includes("tile")) return; // a missing tile is not a failure
      setMapError(message);
    });

    // MapLibre sizes its canvas at construction. If the container is still zero
    // height at that moment, which happens when a grid row has not resolved, the
    // canvas stays 0 by 0 and the map renders nothing with no error anywhere.
    const observer = new ResizeObserver(() => instance.resize());
    observer.observe(node);
    instance.once("load", () => instance.resize());

    return () => {
      observer.disconnect();
      instance.remove();
      map.current = null;
    };
  }, []);

  useEffect(() => {
    const instance = map.current;
    if (!instance) return;

    const draw = () => {
      const detectionData = {
        type: "FeatureCollection" as const,
        features: visible.map((d) => ({
          type: "Feature" as const,
          geometry: { type: "Point" as const, coordinates: [d.lon, d.lat] },
          properties: {
            id: d.id,
            colour: classColour(d.predicted),
            abstains: d.predictionSet.length === 1 ? 0 : 1,
          },
        })),
      };
      const sourceData = {
        type: "FeatureCollection" as const,
        features: sources.map((s) => ({
          type: "Feature" as const,
          geometry: { type: "Point" as const, coordinates: [s.lon, s.lat] },
          properties: { registered: s.registered ? 1 : 0, detections: s.detections },
        })),
      };

      const existing = instance.getSource("detections") as maplibregl.GeoJSONSource | undefined;
      if (existing) {
        existing.setData(detectionData);
        (instance.getSource("sources") as maplibregl.GeoJSONSource).setData(sourceData);
        return;
      }

      instance.addSource("detections", { type: "geojson", data: detectionData });
      instance.addSource("sources", { type: "geojson", data: sourceData });
      instance.addLayer({
        id: "sources-ring",
        type: "circle",
        source: "sources",
        paint: {
          "circle-radius": 7,
          "circle-color": "rgba(0,0,0,0)",
          "circle-stroke-width": 2,
          "circle-stroke-color": [
            "case", ["==", ["get", "registered"], 1], "#63635e", "#b00020",
          ],
        },
      });
      instance.addLayer({
        id: "detections",
        type: "circle",
        source: "detections",
        paint: {
          // Radius and opacity both scale with zoom. At country zoom a fixed
          // radius made Punjab a solid dark polygon that reads as a choropleth
          // rather than as thousands of overlapping points. Small and translucent
          // at low zoom lets overlap accumulate into visible density instead.
          "circle-radius": [
            "interpolate", ["linear"], ["zoom"],
            3, 1.1,
            5, 1.8,
            7, 3.2,
            10, 5.5,
            13, 8,
          ],
          "circle-color": ["get", "colour"],
          "circle-opacity": [
            "interpolate", ["linear"], ["zoom"], 3, 0.42, 7, 0.68, 11, 0.88,
          ],
          // A zoom expression must sit at the top level of a paint property, so
          // the interpolate wraps the case rather than the other way round.
          // MapLibre rejects the nested form outright.
          "circle-stroke-width": [
            "interpolate", ["linear"], ["zoom"],
            3, ["case", ["==", ["get", "abstains"], 1], 0.5, 0],
            8, ["case", ["==", ["get", "abstains"], 1], 1.4, 0],
          ],
          "circle-stroke-color": "#1b1b1a",
        },
      });
      instance.on("click", "detections", (event) => {
        const id = event.features?.[0]?.properties?.["id"];
        const found = detections.find((d) => d.id === id);
        if (found) setSelected(found);
      });
      instance.on("mouseenter", "detections", () => {
        instance.getCanvas().style.cursor = "pointer";
      });
      instance.on("mouseleave", "detections", () => {
        instance.getCanvas().style.cursor = "";
      });
    };

    if (instance.isStyleLoaded()) draw();
    else instance.once("load", draw);
  }, [visible, sources, detections]);

  const toggle = (name: string) => {
    const next = new Set(active);
    if (next.has(name)) next.delete(name);
    else next.add(name);
    setActive(next);
  };

  const download = () => {
    const blob = new Blob([toCsv(visible)], { type: "text/csv" });
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = "agninetra-detections.csv";
    anchor.click();
    URL.revokeObjectURL(url);
  };

  const unregistered = sources.filter((s) => !s.registered);

  return (
    <>
      <div className="body">
        <div className="mapwrap">
          <div className="map" ref={container} />
          {BASEMAP_CONFIGURED ? null : (
            <div className="basemapnotice">
              <strong>No basemap configured. This is not a bug.</strong> The
              detections and persistent sources on this map are real; the ground
              beneath them is blank because{" "}
              <code>NEXT_PUBLIC_BASEMAP_TILES</code> is unset.
              <br />
              To add a basemap, set that variable to a comma separated list of tile
              URL templates from a provider whose terms allow it, and set{" "}
              <code>NEXT_PUBLIC_BASEMAP_ATTRIBUTION</code> to their required notice.
              MapTiler and Stadia Maps both work and both need a free account.
              <br />
              There is no default because tiles were previously taken straight from
              openstreetmap.org, which its usage policy does not permit for a
              distributed application, and a silent fallback would ship that
              violation rather than surface it. See D69.
            </div>
          )}
          {shownError ? (
            <div className="maperror">
              <strong>Map unavailable</strong>
              <p>{shownError}</p>
              <p>
                The detections are still loaded and every panel, filter and export
                works. This message replaces the map rather than hiding it, for the
                same reason an unmeasured value reads {"not measured"} rather than
                being omitted.
              </p>
            </div>
          ) : null}
        </div>
        <aside className="aside">
          <EvidencePanel
            detection={selected}
            nominal={manifest.conformalNominal}
            heldOutGroup={manifest.heldOutGroup}
            heldOutCoverage={heldOutCoverage}
          />

          <div className="card">
            <h3>Persistent sources</h3>
            <div className="row">
              <span className="k">recurring locations</span>
              <span className="v">{sources.length}</span>
            </div>
            <div className="row">
              <span className="k">with no registry match</span>
              <span className="v" style={{ color: "#b00020" }}>
                {unregistered.length}
              </span>
            </div>
            <p style={{ fontSize: "0.74rem", color: "var(--muted)" }}>
              <strong>Scope:</strong> {manifest.persistentSourceScope}
            </p>
            <p style={{ fontSize: "0.74rem", color: "var(--muted)" }}>
              {manifest.persistentSourceRule}
            </p>
            <div className="srlist">
              {unregistered.map((s) => (
                <button
                  className="srrow"
                  key={`${s.lon},${s.lat}`}
                  onClick={() => map.current?.flyTo({ center: [s.lon, s.lat], zoom: 11 })}
                  type="button"
                >
                  <span>
                    {s.state ?? "unassigned"} {s.lat.toFixed(3)}, {s.lon.toFixed(3)}
                  </span>
                  <span>
                    {s.detections} det, spread {metres(s.spreadM)}, nearest{" "}
                    {metres(s.nearestAssetM)}
                  </span>
                </button>
              ))}
            </div>
          </div>

          <div className="card">
            <h3>Export</h3>
            <p style={{ fontSize: "0.76rem", color: "var(--muted)" }}>
              {count(visible.length)} detections match the current filters.
              The export carries the posterior, the prediction set and the
              applicability flag, and writes {"not measured"} where a value was not
              computed.
            </p>
            <button onClick={download} type="button">
              Download filtered CSV
            </button>
          </div>
        </aside>
      </div>

      <div className="scrub">
        <div className="legend">
          {CLASSES.map((name) => (
            <button
              aria-pressed={active.has(name)}
              key={name}
              onClick={() => toggle(name)}
              type="button"
            >
              <i style={{ background: classColour(name) }} />
              {name}
            </button>
          ))}
          <button
            aria-pressed={abstainOnly}
            onClick={() => setAbstainOnly(!abstainOnly)}
            type="button"
          >
            abstentions only
          </button>
        </div>
        <label htmlFor="scrubber" style={{ fontSize: "0.78rem" }}>
          {dayIndex < 0 ? "all dates" : dates[dayIndex]}
        </label>
        <input
          id="scrubber"
          max={dates.length - 1}
          min={-1}
          onChange={(event) => setDayIndex(Number(event.target.value))}
          type="range"
          value={dayIndex}
        />
        <span style={{ fontSize: "0.78rem", color: "var(--muted)" }}>
          <strong>Dots</strong>: {count(visible.length)} of {count(detections.length)}{" "}
          sampled detections, <strong>group_a held out states only</strong>. Black
          outline is an abstention.
          {" | "}
          <strong>Rings</strong>: {sources.length} persistent sources,{" "}
          <strong>computed over all of India</strong>. Red means no registry match.
          The two layers have different scopes.
        </span>
      </div>
    </>
  );
}
