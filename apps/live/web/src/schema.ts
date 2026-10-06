import { z } from "zod";

// Mirror of the feed the Python pipeline writes. Parsed, never cast: a shape change on
// the Python side must fail here as an error rather than reach the screen as a wrong
// number.

const share = z.number().min(0).max(1).nullable();

// The template names the pipeline allows, feed.py TEMPLATES and COMMENTARY. A test on the
// Python side fails if either list gains a name this file does not carry.
const NetuTemplate = z.enum([
  "polar_all_out",
  "both_quiet",
  "insat_share",
  "polar_share",
  "quiet",
  "worried",
  "data_late",
]);
const CommentaryTemplate = z.enum(["maiden", "insat_up", "polar_in_pavilion", "polar_late", "not_yet"]);

export const Cell = z.object({
  cell: z.string(),
  centre: z.tuple([z.number(), z.number()]),
  state: z.string().nullable(),
  district: z.string().nullable(),
  class: z.enum(["agricultural", "industrial", "flare", "unclassified"]),
  how_sure: z.enum(["low", "medium"]),
  seen_by: z.array(z.enum(["polar", "insat"])),
  evening: z.boolean(),
  first_seen_ist: z.string().regex(/^\d{2}:\d{2}$/),
}).strict();

export const Over = z.object({
  over: z.string(),
  polar_share: share,
  insat_share: share,
  polar_new: z.boolean(),
  insat_new: z.boolean(),
});

// Tomorrow's PM2.5 for each city Netu can follow. Optional, because evenings built before
// the city list existed still have to load.
export const Air = z.object({
  city: z.string(),
  lon: z.number().min(60).max(100).optional(),
  lat: z.number().min(0).max(40).optional(),
  pm25_24h_mean: z.number().min(0).nullable(),
  cpcb_category: z.string().nullable(),
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
    // Counts arrived after the first feeds; without them the split is worked out from shares.
    cells_total: z.number().int().min(0).optional(),
    cells_both: z.number().int().min(0).optional(),
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
  netu: z.array(z.object({ template: NetuTemplate, text: z.string() })),
  commentary: z.array(z.object({ over: z.string(), template: CommentaryTemplate, text: z.string() })),
  tomorrow: z.object({
    city: z.string(),
    forecast_date: z.string(),
    pm25_24h_mean: z.number().nullable(),
    cpcb_category: z.string().nullable(),
    evening_fire_cells: z.number().int(),
    school_hybrid: z.literal("not measured"),
    source: z.string(),
  }),
  air: z.array(Air).optional(),
  heatle: z.object({
    clues: z.array(z.record(z.string(), z.unknown())),
    answer: z.string(),
    choices: z.array(z.string()),
  }),
  wind: z
    .object({
      grid_deg: z.number(),
      hours_ist: z.array(z.string()),
      points: z.array(
        z.tuple([z.number(), z.number(), z.array(z.tuple([z.number().min(0).nullable(), z.number().min(0).max(360).nullable()]))]),
      ),
      source: z.string(),
    })
    .nullable(),
  attribution: z.array(z.string()).min(1),
  caveats: z.array(z.string()).min(1),
});

const Ring = z.array(z.tuple([z.number(), z.number()]));

export const Boundaries = z.object({
  type: z.literal("FeatureCollection"),
  attribution: z.string(),
  features: z.array(
    z.object({
      properties: z.object({ kind: z.enum(["state", "district", "country"]), name: z.string() }),
      geometry: z.discriminatedUnion("type", [
        z.object({ type: z.literal("Polygon"), coordinates: z.array(Ring) }),
        z.object({ type: z.literal("MultiPolygon"), coordinates: z.array(z.array(Ring)) }),
      ]),
    }),
  ),
});

export type Feed = z.infer<typeof Feed>;
export type Cell = z.infer<typeof Cell>;
export type Air = z.infer<typeof Air>;
export type Boundaries = z.infer<typeof Boundaries>;
export type Wind = NonNullable<Feed["wind"]>;
