import { z } from "zod";
import { HeatleRecord, PetRecord, SwipeRecord, Theme, VisitRecord } from "./records";
import { recall, remember } from "./store";

// Without an account, everything Live keeps lives on one device, D139, so moving to another
// browser is a file the player carries themselves: exported here, imported there. The same
// merge rule runs on the server when a signed in player syncs, D142.

export const BackupData = z.object({
  pet: PetRecord.optional(),
  heatle: HeatleRecord.optional(),
  swipe: SwipeRecord.optional(),
  visits: VisitRecord.optional(),
  city: z.string().max(40).optional(),
  theme: Theme.optional(),
});
export type BackupData = z.infer<typeof BackupData>;

export const Backup = z.object({
  app: z.literal("agninetra-live"),
  version: z.literal(1),
  exported: z.string(),
  data: BackupData,
});

export const MAX_BACKUP_BYTES = 1_000_000;

// Two histories become one: every day and every answer from both, the larger experience,
// and the incoming city and theme, since the player chose to bring them.
export function merge(current: BackupData, incoming: BackupData): BackupData {
  const pick = <T>(a: T | undefined, b: T | undefined): T | undefined => b ?? a;
  const xp = Math.max(current.pet?.xp ?? 0, incoming.pet?.xp ?? 0);
  return {
    pet: { xp },
    heatle: { ...current.heatle, ...incoming.heatle },
    swipe: { ...current.swipe, ...incoming.swipe },
    visits: { ...current.visits, ...incoming.visits },
    city: pick(current.city, incoming.city),
    theme: pick(current.theme, incoming.theme),
  };
}

export function collect(): BackupData {
  const optional = <T>(key: string, schema: z.ZodType<T>): T | undefined =>
    recall<T | undefined>(key, (v) => schema.parse(v), undefined);
  return {
    pet: optional("pet", PetRecord),
    heatle: optional("heatle", HeatleRecord),
    swipe: optional("swipe", SwipeRecord),
    visits: optional("visits", VisitRecord),
    city: optional("city", z.string()),
    theme: optional("theme", Theme),
  };
}

export function exportFile(): Blob {
  const backup = { app: "agninetra-live", version: 1, exported: new Date().toISOString(), data: collect() };
  return new Blob([JSON.stringify(backup, null, 1)], { type: "application/json" });
}

export async function importFile(file: File): Promise<void> {
  if (file.size > MAX_BACKUP_BYTES) throw new Error("That file is too large to be an AgniNetra backup.");
  const parsed = Backup.safeParse(JSON.parse(await file.text()));
  if (!parsed.success) throw new Error("That file is not an AgniNetra backup.");
  const merged = merge(collect(), parsed.data.data);
  for (const [key, value] of Object.entries(merged)) {
    if (value !== undefined) remember(key, value);
  }
}
