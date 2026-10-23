import type { BackupData } from "./backup";

export function sameValue(left: unknown, right: unknown): boolean {
  if (left === right) return true;
  if (left === null || right === null || typeof left !== "object" || typeof right !== "object") return false;
  if (Array.isArray(left) !== Array.isArray(right)) return false;
  const entries = Object.entries(left).filter(([, value]) => value !== undefined);
  const other = new Map(Object.entries(right).filter(([, value]) => value !== undefined));
  return entries.length === other.size && entries.every(([key, value]) => other.has(key) && sameValue(value, other.get(key)));
}

function history<T>(sent: Record<string, T> | undefined, current: Record<string, T> | undefined, reply: Record<string, T> | undefined): Record<string, T> {
  const merged = { ...sent, ...reply };
  for (const [key, value] of Object.entries(current ?? {})) {
    if (!sameValue(sent?.[key], value)) merged[key] = value;
  }
  return merged;
}

export function reconcile(sent: BackupData, current: BackupData, reply: BackupData): BackupData {
  return {
    pet: { xp: Math.max(current.pet?.xp ?? 0, reply.pet?.xp ?? 0) },
    heatle: history(sent.heatle, current.heatle, reply.heatle),
    swipe: history(sent.swipe, current.swipe, reply.swipe),
    visits: history(sent.visits, current.visits, reply.visits),
    city: sameValue(sent.city, current.city) ? reply.city ?? sent.city : current.city,
    theme: sameValue(sent.theme, current.theme) ? reply.theme ?? sent.theme : current.theme,
  };
}
