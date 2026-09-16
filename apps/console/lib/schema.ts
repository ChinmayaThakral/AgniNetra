import { z } from "zod";

/**
 * Every file the console reads is parsed through a schema, never cast. The
 * exporter and the console are separate programs and a silent shape change
 * between them would surface as a wrong number on screen rather than an error.
 */

export const detectionSchema = z.object({
  id: z.string(),
  lon: z.number(),
  lat: z.number(),
  date: z.string(),
  state: z.string().nullable(),
  frpMw: z.number().nullable(),
  isNight: z.boolean(),
  weakLabel: z.string(),
  predicted: z.string(),
  posterior: z.record(z.string(), z.number()),
  predictionSet: z.array(z.string()),
  // Null where a feature is unobserved, so the row was never assessed. Parsing
  // this as a plain boolean would read "not assessed" as "inside". D68.
  outsideApplicability: z.boolean().nullable(),
  priorCount90d: z.number(),
  priorCount30d: z.number(),
  nightFraction90d: z.number().nullable(),
  meanGapDays: z.number().nullable(),
  // Coarse band, not a distance. The EOG layer is not redistributable and
  // thousands of exact distances are trilaterable back to the flare positions.
  // D69.
  nearestFlareBand: z.enum(["under 1 km", "1 to 5 km", "5 to 20 km", "over 20 km"]).nullable(),
  nearestIndustrialM: z.number().nullable(),
  nearestGemM: z.number().nullable(),
});

export const sourceSchema = z.object({
  lon: z.number(),
  lat: z.number(),
  state: z.string().nullable(),
  detections: z.number(),
  maxPriors: z.number(),
  nightFraction: z.number(),
  nearestAssetM: z.number().nullable(),
  registered: z.boolean(),
  spreadM: z.number(),
});

const classMetricSchema = z.object({
  precision: z.number(),
  recall: z.number(),
  f1: z.number(),
  support: z.number(),
});

export const metricsSchema = z.object({
  source: z.string(),
  seed: z.number(),
  resampling: z.string(),
  trainedClasses: z.array(z.string()),
  wildfire: z.string(),
  leakageMacroF1: z.number(),
  cleanMacroF1: z.number(),
  perGroup: z.record(
    z.string(),
    z.object({ macroF1: z.number(), classes: z.record(z.string(), classMetricSchema) }),
  ),
  uncertainty: z.record(
    z.string(),
    z.object({
      coverage: z.number(),
      nominal: z.number(),
      mean_set_size: z.number(),
      singleton_fraction: z.number(),
      empty_fraction: z.number(),
      outside_aoa_fraction: z.number(),
      accuracy_inside_aoa: z.number().nullable(),
      accuracy_outside_aoa: z.number().nullable(),
    }),
  ),
  b2Industrial: z.object({
    precision: z.number(),
    recall: z.number(),
    f1: z.number(),
    sample: z.number(),
    clusters: z.number(),
    persistent_clusters: z.number(),
  }),
  notMeasured: z.record(z.string(), z.string()),
});

export const manifestSchema = z.object({
  generatedBy: z.string(),
  heldOutGroup: z.string(),
  heldOutStates: z.array(z.string()),
  samplingRule: z.string(),
  totalDetectionsInStore: z.number(),
  indiaAssignedDetections: z.number(),
  sampledDetections: z.number(),
  windows: z.array(z.string()),
  snapshots: z.record(z.string(), z.string()),
  conformalNominal: z.number(),
  applicabilityQuantile: z.number(),
  persistentSourceRule: z.string(),
  persistentSourceScope: z.string(),
  detectionScope: z.string(),
  clusterRadiusSweep: z.array(z.array(z.number())),
  attribution: z.array(
    z.object({ name: z.string(), detail: z.string(), url: z.string() }),
  ),
  externalExtents: z.record(z.string(), z.array(z.number())),
});


// Phase 5, the geostationary window. Parsed rather than cast, like every other file
// the Python side produces, so a field the exporter stops emitting fails here at the
// boundary instead of arriving as undefined somewhere further in.
export const geostationarySchema = z.object({
  generatedBy: z.string(),
  windows: z.array(
    z.object({
      key: z.string(),
      label: z.string(),
      span: z.string(),
      granules: z.number(),
      slotsPresent: z.number(),
      slotsExpected: z.number(),
      hoursObserved: z.number(),
      detections: z.number(),
      detectionsInStubbleBox: z.number(),
      eveningSharePct: z.number(),
      polarOverpassSharePct: z.number(),
      meanByHour: z.array(z.number().nullable()),
      states: z.array(
        z.object({
          name: z.string(),
          detections: z.number(),
          perGranule: z.number(),
          eveningSharePct: z.number(),
          polarOverpassSharePct: z.number(),
          peakHourIst: z.number(),
        }),
      ),
      collocation: z.array(
        z.object({
          radiusM: z.number(),
          checkable: z.number(),
          corroborated: z.number(),
          ratePct: z.number(),
        }),
      ),
      polarDetections: z.number(),
    }),
  ),
  detectorChange: z.object({
    before: z.number(),
    after: z.number(),
    stubbleBoxBefore: z.number(),
    stubbleBoxAfter: z.number(),
    rule: z.string(),
  }),
  caveats: z.array(z.string()),
});

export type Detection = z.infer<typeof detectionSchema>;
export type Source = z.infer<typeof sourceSchema>;
export type Metrics = z.infer<typeof metricsSchema>;
export type Manifest = z.infer<typeof manifestSchema>;
export type Geostationary = z.infer<typeof geostationarySchema>;
