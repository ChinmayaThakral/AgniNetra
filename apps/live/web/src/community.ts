import { z } from "zod";
import { BackupData, collect } from "./backup";
import { recall, remember } from "./store";

// Talking to the Live server's community API: Google sign in, the session, and keeping a
// player's game data in step across browsers. Sign in uses Google's own redirect, so no
// script from Google ever runs on this page.

const GOOGLE_AUTH = "https://accounts.google.com/o/oauth2/v2/auth";

export const Config = z.object({ client_id: z.string(), qualify_needed: z.number(), max_clues: z.number() });
export type Config = z.infer<typeof Config>;

export const Profile = z.object({
  email: z.string(),
  correct: z.number(),
  attempts: z.number(),
  qualified: z.boolean(),
  rounds_left: z.number(),
  answered: z.number(),
  data: BackupData.nullable().optional(),
});
export type Profile = z.infer<typeof Profile>;

export class ApiError extends Error {
  constructor(
    readonly status: number,
    message: string,
  ) {
    super(message);
  }
}

function token(): string | null {
  return recall<string | null>("session", (v) => z.string().parse(v), null);
}

export function signedIn(): boolean {
  return token() !== null;
}

export async function api<T>(method: string, path: string, parse: (v: unknown) => T, body?: unknown): Promise<T> {
  const headers: Record<string, string> = {};
  const session = token();
  if (session) headers.Authorization = `Bearer ${session}`;
  if (body !== undefined) headers["Content-Type"] = "application/json";
  const response = await fetch(path, { method, headers, body: body === undefined ? undefined : JSON.stringify(body) });
  const value: unknown = await response.json().catch(() => ({}));
  if (!response.ok) {
    const message = z.object({ error: z.string() }).safeParse(value);
    if (response.status === 401) remember("session", null);
    throw new ApiError(response.status, message.success ? message.data.error : `The server answered ${response.status}.`);
  }
  return parse(value);
}

export async function config(): Promise<Config | null> {
  try {
    return await api("GET", "api/config", (v) => Config.parse(v));
  } catch {
    return null;
  }
}

function randomString(): string {
  const bytes = new Uint8Array(24);
  crypto.getRandomValues(bytes);
  return Array.from(bytes, (b) => b.toString(16).padStart(2, "0")).join("");
}

export function signIn(clientId: string): void {
  const nonce = randomString();
  remember("nonce", nonce);
  const params = new URLSearchParams({
    client_id: clientId,
    redirect_uri: `${window.location.origin}/`,
    response_type: "id_token",
    scope: "openid email",
    nonce,
    prompt: "select_account",
  });
  window.location.assign(`${GOOGLE_AUTH}?${params.toString()}`);
}

// Google returns to this page with the signed token in the address fragment. It is handed
// to the server once, then wiped from the address bar and from history.
export async function finishSignIn(): Promise<Profile | null> {
  const fragment = new URLSearchParams(window.location.hash.slice(1));
  const idToken = fragment.get("id_token");
  if (!idToken) return null;
  window.history.replaceState(null, "", window.location.pathname + window.location.search);
  const nonce = recall<string | null>("nonce", (v) => z.string().parse(v), null);
  remember("nonce", null);
  if (!nonce) return null;
  const reply = await api("POST", "api/session", (v) => Profile.extend({ token: z.string() }).parse(v), {
    id_token: idToken,
    nonce,
  });
  remember("session", reply.token);
  await syncData();
  return reply;
}

export async function signOut(): Promise<void> {
  await api("DELETE", "api/session", () => null).catch(() => null);
  remember("session", null);
}

export async function deleteAccount(): Promise<void> {
  await api("DELETE", "api/me", () => null);
  remember("session", null);
}

// The server merges this browser's game data with what it holds, by the same rule as a
// backup import, and both sides end up with the union.
export async function syncData(): Promise<void> {
  if (!signedIn()) return;
  const reply = await api("PUT", "api/me/data", (v) => z.object({ data: BackupData }).parse(v), { data: collect() });
  for (const [key, value] of Object.entries(reply.data)) {
    if (value !== undefined) remember(key, value);
  }
}

export async function me(): Promise<Profile> {
  return api("GET", "api/me", (v) => Profile.parse(v));
}

// Qualifying: the server deals each round a clue at a time and keeps the answer to itself.

const Clue = z.record(z.string(), z.unknown());

export const RoundView = z.object({
  round: z.string(),
  clues: z.array(Clue),
  total_clues: z.number().int(),
  choices: z.array(z.string()),
});
export type RoundView = z.infer<typeof RoundView>;

export const RoundEnd = Profile.omit({ data: true }).extend({
  right: z.boolean(),
  counted: z.boolean(),
  answer: z.string(),
  clues: z.array(Clue),
});
export type RoundEnd = z.infer<typeof RoundEnd>;

const GuessReply = z.union([RoundEnd, RoundView.extend({ right: z.literal(false) })]);

export function startRound(): Promise<RoundView> {
  return api("POST", "api/qualify/start", (v) => RoundView.parse(v), {});
}

export function nextClue(round: string): Promise<RoundView> {
  return api("POST", "api/qualify/clue", (v) => RoundView.parse(v), { round });
}

export function guess(round: string, answer: string): Promise<z.infer<typeof GuessReply>> {
  return api("POST", "api/qualify/guess", (v) => GuessReply.parse(v), { round, answer });
}

// Labelling: what is known about each unidentified spot comes with it.

export const Nearby = z.object({
  what: z.string(),
  name: z.string().nullable(),
  km: z.number(),
  source: z.string(),
});

export const SpotDetails = z.object({
  lon: z.number(),
  lat: z.number(),
  state: z.string().nullable(),
  subdistrict: z.string().optional(),
  detections: z.number().int(),
  night_share: z.number(),
  spread_m: z.number(),
  first_seen: z.string().optional(),
  last_seen: z.string().optional(),
  days_seen: z.number().int().optional(),
  by_month: z.array(z.number().int()).length(12).optional(),
  observed_months: z.array(z.number().int().min(1).max(12)).optional(),
  median_frp_mw: z.number().optional(),
  satellites: z.array(z.string()).optional(),
  nearby: z.array(Nearby),
});
export type SpotDetails = z.infer<typeof SpotDetails>;

export const Spot = z.object({
  id: z.string().regex(/^s[0-9a-f]{10}$/),
  chip: z.string().regex(/^chips\/s[0-9a-f]{10}\.webp$/),
  acquired: z.string(),
  wide: z.string().regex(/^chips\/s[0-9a-f]{10}_wide\.webp$/).optional(),
  details: SpotDetails.optional(),
});
export type Spot = z.infer<typeof Spot>;

export const Queue = z.object({
  item: Spot.nullable(),
  kinds: z.array(z.string()).optional(),
  answered: z.number().int(),
  total: z.number().int(),
});
export type Queue = z.infer<typeof Queue>;

export type Label = "industry" | "not industry" | "unsure";

export function nextSpot(): Promise<Queue> {
  return api("GET", "api/swipe/next", (v) => Queue.parse(v));
}

export function label(item: string, answer: Label, kind?: string): Promise<Queue> {
  return api("POST", "api/swipe/answer", (v) => Queue.parse(v), kind ? { item, answer, kind } : { item, answer });
}
