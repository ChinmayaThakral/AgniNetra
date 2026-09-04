"use client";

import maplibregl from "maplibre-gl";
import "maplibre-gl/dist/maplibre-gl.css";
import { useEffect, useMemo, useRef, useState } from "react";

import { classColour, count, metres } from "@/lib/format";
import type { Detection, Manifest, Source } from "@/lib/schema";
import { EvidencePanel } from "./evidence-panel";

const CLASSES = ["flare", "industrial", "agricultural"] as const;

/** Basemap without an API key, so the console runs with no credential. */
const STYLE = {
  version: 8 as const,
  sources: {
    carto: {
      type: "raster" as const,
      tiles: ["https://a.basemaps.cartocdn.com/light_all/{z}/{x}/{y}.png"],
      tileSize: 256,
      attribution:
        '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors &copy; <a href="https://carto.com/attributions">CARTO</a>',
    },
  },
  layers: [{ id: "carto", type: "raster" as const, source: "carto" }],
};

function toCsv(rows: Detection[]): string {
  const header = [
    "id", "lon", "lat", "date", "state", "frp_mw", "is_night", "weak_label",
    "predicted", "prediction_set", "outside_applicability", "prior_count_90d",
    "night_fraction_90d", "nearest_flare_m", "nearest_industrial_m", "nearest_gem_m",
  ];
  const lines = rows.map((d) =>
    [
      d.id, d.lon, d.lat, d.date, d.state ?? "", d.frpMw ?? "not measured",
      d.isNight, d.weakLabel, d.predicted, d.predictionSet.join(" "),
      d.outsideApplicability, d.priorCount90d,
      d.nightFraction90d ?? "not measured",
      d.nearestFlareM ?? "not measured",
      d.nearestIndustrialM ?? "not measured",
      d.nearestGemM ?? "not measured",
    ].join(","),
  );
  return [header.join(","), ...lines].join("\n");
}

export function ConsoleClient({
  detections,
  sources,
  manifest,
}: {
  detections: Detection[];
  sources: Source[];
  manifest: Manifest;
}) {
  const container = useRef<HTMLDivElement | null>(null);
  const map = useRef<maplibregl.Map | null>(null);
  const [selected, setSelected] = useState<Detection | null>(null);
  const [active, setActive] = useState<Set<string>>(new Set(CLASSES));
  const [abstainOnly, setAbstainOnly] = useState(false);
  const [dayIndex, setDayIndex] = useState<number>(-1);

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
    if (!container.current || map.current) return;
    map.current = new maplibregl.Map({
      container: container.current,
      style: STYLE,
      center: [80.5, 22.5],
      zoom: 3.9,
    });
    map.current.addControl(new maplibregl.NavigationControl({}), "top-right");
    map.current.addControl(new maplibregl.ScaleControl({ unit: "metric" }));
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
          "circle-radius": ["interpolate", ["linear"], ["zoom"], 3, 2.4, 10, 6],
          "circle-color": ["get", "colour"],
          "circle-opacity": 0.85,
          "circle-stroke-width": ["case", ["==", ["get", "abstains"], 1], 1.4, 0],
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
        </div>
        <aside className="aside">
          <EvidencePanel detection={selected} />

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
                    {s.detections} det, nearest {metres(s.nearestAssetM)}
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
          {count(visible.length)} of {count(detections.length)} shown
          {" | "}
          circles outlined in black are abstentions
          {" | "}
          red rings are persistent sources with no registry match
        </span>
      </div>
    </>
  );
}
