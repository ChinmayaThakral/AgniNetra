import { z } from "zod";

// Mirror of the feed the Python pipeline writes. Parsed, never cast: a shape change on
// the Python side must fail here as an error rather than reach the screen as a wrong
// number.

const share = z.number().min(0).max(1).nullable();

export const Cell = z.object({
  cell: z.string(),
  centre: z.tuple([z.number(), z.number()]),
  state: z.string().nullable(),
  district: z.string().nullable(),
  class: z.enum(["agricultural", "industrial", "flare", "unclassified"]),
  how_sure: z.enum(["low", "medium"]),
  seen_by: z.array(z.enum(["polar", "insat"])),
  evening: z.boolean(),
});

export const Over = z.object({
  over: z.string(),
  polar_share: share,
  insat_share: share,
  polar_new: z.boolean(),
  insat_new: z.boolean(),
});

export const Feed = z.object({
  schema: z.literal("agninetra-live/1"),
  generated_utc: z.string(),
  evening_ist: z.string(),
  latency: z.object({
    insat_newest_utc: z.string().nullable(),
    insat_delay_hours: z.number().nullable(),
    polar_newest_utc: z.string().nullable(),
  }),
  match: z.object({
    window_ist: z.string(),
    polar_share: share,
    insat_share: share,
    polar_last_seen_ist: z.string().nullable(),
    insat_last_seen_ist: z.string().nullable(),
    overs: z.array(Over),
  }),
  cells: z.array(Cell),
  districts: z.array(
    z.object({
      state: z.string().nullable(),
      district: z.string(),
      cells: z.number().int(),
      polar_share: share,
      insat_share: share,
      evening_share: share,
    }),
  ),
  netu: z.array(z.object({ template: z.string(), text: z.string() })),
  tomorrow: z.object({
    city: z.string(),
    forecast_date: z.string(),
    pm25_24h_mean: z.number().nullable(),
    cpcb_category: z.string().nullable(),
    evening_fire_cells: z.number().int(),
    school_hybrid: z.literal("not measured"),
    source: z.string(),
  }),
  heatle: z.object({
    clues: z.array(z.record(z.string(), z.unknown())),
    answer: z.string(),
    choices: z.array(z.string()),
  }),
  attribution: z.array(z.string()).min(1),
  caveats: z.array(z.string()).min(1),
});

const Ring = z.array(z.tuple([z.number(), z.number()]));

export const Boundaries = z.object({
  type: z.literal("FeatureCollection"),
  attribution: z.string(),
  features: z.array(
    z.object({
      properties: z.object({ kind: z.enum(["state", "district"]), name: z.string() }),
      geometry: z.discriminatedUnion("type", [
        z.object({ type: z.literal("Polygon"), coordinates: z.array(Ring) }),
        z.object({ type: z.literal("MultiPolygon"), coordinates: z.array(z.array(Ring)) }),
      ]),
    }),
  ),
});

export type Feed = z.infer<typeof Feed>;
export type Cell = z.infer<typeof Cell>;
export type Boundaries = z.infer<typeof Boundaries>;
