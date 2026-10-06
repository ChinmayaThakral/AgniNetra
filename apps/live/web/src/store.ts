// The only module that touches browser storage, by the owner's decision D139: a player's
// own history stays on this phone and is never sent anywhere. Every value is parsed on the
// way back in, and any failure, private mode, a full disk or a value from an older
// version, falls back to the default instead of breaking the page.

const PREFIX = "agninetra.v1.";

export function recall<T>(key: string, parse: (value: unknown) => T, fallback: T): T {
  try {
    const raw = window.localStorage.getItem(PREFIX + key);
    return raw === null ? fallback : parse(JSON.parse(raw));
  } catch {
    return fallback;
  }
}

export function remember(key: string, value: unknown): void {
  try {
    window.localStorage.setItem(PREFIX + key, JSON.stringify(value));
  } catch {
    // Storage can be full or switched off. The game still works for this visit.
  }
}
