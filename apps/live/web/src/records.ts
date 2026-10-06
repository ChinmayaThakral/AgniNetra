import { z } from "zod";

// The shapes of everything Live keeps on the phone, in one place. Each is parsed on the
// way back in, so a value from an older version falls back to empty rather than breaking.

export const HeatleRecord = z.record(z.string(), z.object({ solved: z.boolean(), clue: z.number().int().min(0) }));
export const SwipeRecord = z.record(z.string(), z.object({ a: z.enum(["factory", "flare", "unsure", "industry", "not industry"]), at: z.string() }));
// Each day the app was opened, with the CPCB category forecast that day for the player's city.
export const PetRecord = z.object({ xp: z.number().int().min(0) });
export const Theme = z.enum(["light", "dark"]);
export type Theme = z.infer<typeof Theme>;
export const VisitRecord = z.record(z.string(), z.string().nullable());

export const BAD_AIR = ["Poor", "Very Poor", "Severe"];
