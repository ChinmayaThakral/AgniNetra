import { readFile } from "node:fs/promises";
import path from "node:path";

import {
  detectionSchema,
  manifestSchema,
  metricsSchema,
  sourceSchema,
  type Detection,
  type Manifest,
  type Metrics,
  type Source,
} from "./schema";
import { z } from "zod";

const DATA_DIR = path.join(process.cwd(), "public", "data");

async function readJson(name: string): Promise<unknown> {
  return JSON.parse(await readFile(path.join(DATA_DIR, name), "utf8"));
}

export async function loadDetections(): Promise<Detection[]> {
  return z.array(detectionSchema).parse(await readJson("detections.json"));
}

export async function loadSources(): Promise<Source[]> {
  return z.array(sourceSchema).parse(await readJson("sources.json"));
}

export async function loadMetrics(): Promise<Metrics> {
  return metricsSchema.parse(await readJson("metrics.json"));
}

export async function loadManifest(): Promise<Manifest> {
  return manifestSchema.parse(await readJson("manifest.json"));
}
