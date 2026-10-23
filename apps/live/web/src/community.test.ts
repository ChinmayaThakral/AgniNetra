import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const stored = vi.hoisted(() => new Map<string, unknown>());
vi.mock("./store", () => ({
  recall: <T>(key: string, parse: (value: unknown) => T, fallback: T): T => {
    try {
      return stored.has(key) ? parse(structuredClone(stored.get(key))) : fallback;
    } catch {
      return fallback;
    }
  },
  remember: (key: string, value: unknown): void => { stored.set(key, structuredClone(value)); },
}));

type Request = { path: string; init: RequestInit; resolve: (value: Response) => void; reject: (reason: Error) => void };
let calls: Request[];
let community: typeof import("./community");

function response(value: unknown, status = 200): Response {
  return new Response(JSON.stringify(value), { status, headers: { "Content-Type": "application/json" } });
}

async function request(index: number): Promise<Request> {
  await vi.waitFor(() => expect(calls.length).toBeGreaterThan(index));
  const call = calls[index];
  if (!call) throw new Error("Expected a mocked request.");
  return call;
}

function body(call: Request): { data: import("./backup").BackupData } {
  return JSON.parse(String(call.init.body));
}

function profile(token: string): Record<string, unknown> {
  return { token, email: "player@example.test", correct: 0, attempts: 0, qualified: false, rounds_left: 10, answered: 0 };
}

async function signInAs(session: string): Promise<void> {
  const index = calls.length;
  stored.set("nonce", "test-nonce");
  window.location.hash = "#id_token=test-id-token";
  const signing = community.finishSignIn();
  (await request(index)).resolve(response(profile(session)));
  const syncing = await request(index + 1);
  syncing.resolve(response(body(syncing)));
  expect(await signing).not.toBeNull();
}

beforeEach(async () => {
  vi.resetModules();
  stored.clear();
  stored.set("session", "session-a");
  calls = [];
  const location = { hash: "", pathname: "/", search: "" };
  vi.stubGlobal("window", { location, history: { replaceState: vi.fn(() => { location.hash = ""; }) } });
  vi.stubGlobal("fetch", vi.fn((path: string, init: RequestInit): Promise<Response> => new Promise((resolve, reject) => {
    calls.push({ path, init, resolve, reject });
  })));
  community = await import("./community");
});

afterEach(() => { vi.unstubAllGlobals(); });

describe("progress requests", () => {
  it("preserves progress changed during a delayed response and uploads the reconciled snapshot", async () => {
    stored.set("pet", { xp: 10 });
    stored.set("heatle", { old: { solved: true, clue: 3 } });
    const syncing = community.syncData();
    const first = await request(0);
    stored.set("pet", { xp: 15 });
    stored.set("heatle", { old: { solved: true, clue: 3 }, local: { solved: true, clue: 2 } });
    first.resolve(response({ data: { pet: { xp: 12 }, heatle: { old: { solved: true, clue: 3 }, remote: { solved: false, clue: 6 } } } }));
    const second = await request(1);
    expect(body(second).data).toMatchObject({ pet: { xp: 15 }, heatle: { local: { solved: true, clue: 2 }, remote: { solved: false, clue: 6 } } });
    second.resolve(response(body(second)));
    expect(await syncing).toBe(true);
    expect(stored.get("pet")).toEqual({ xp: 15 });
    expect(calls).toHaveLength(2);
  });

  it("finds in-flight preference and visit changes without change events", async () => {
    stored.set("city", "Delhi");
    stored.set("theme", "light");
    const syncing = community.syncData();
    const first = await request(0);
    stored.set("city", "Patna");
    stored.set("theme", "dark");
    stored.set("visits", { today: "Poor" });
    first.resolve(response({ data: { city: "Mumbai", theme: "light", visits: { remote: "Good" } } }));
    const second = await request(1);
    expect(body(second).data).toMatchObject({ city: "Patna", theme: "dark", visits: { today: "Poor", remote: "Good" } });
    second.resolve(response(body(second)));
    await syncing;
  });

  it("applies server-only progress without a response-driven upload loop", async () => {
    const syncing = community.syncData();
    (await request(0)).resolve(response({ data: { pet: { xp: 70 }, heatle: { remote: { solved: true, clue: 1 } } } }));
    expect(await syncing).toBe(true);
    expect(stored.get("pet")).toEqual({ xp: 70 });
    expect(calls).toHaveLength(1);
  });

  it("serializes and coalesces overlapping callers, collecting the queued snapshot after reconciliation", async () => {
    const first = community.syncData();
    const call = await request(0);
    const second = community.syncData();
    const third = community.syncData();
    expect(second).toBe(first);
    expect(third).toBe(first);
    expect(calls).toHaveLength(1);
    call.resolve(response({ data: { city: "Patna", pet: { xp: 20 } } }));
    const followup = await request(1);
    expect(body(followup).data).toMatchObject({ city: "Patna", pet: { xp: 20 } });
    followup.resolve(response(body(followup)));
    expect(await Promise.all([first, second, third])).toEqual([true, true, true]);
    expect(calls).toHaveLength(2);
  });

  it.each(["network", "invalid reply"])("releases a failed runner for retry after %s", async (failure) => {
    stored.set("pet", { xp: 12 });
    const syncing = community.syncData();
    const failed = expect(syncing).rejects.toThrow();
    const call = await request(0);
    if (failure === "network") call.reject(new TypeError("Connection lost"));
    else call.resolve(response({ data: { pet: { xp: -1 } } }));
    await failed;
    expect(stored.get("pet")).toEqual({ xp: 12 });
    const retried = community.syncData();
    const next = await request(1);
    next.resolve(response(body(next)));
    expect(await retried).toBe(true);
  });

  it("skips signed-out calls without a request or success indication", async () => {
    stored.set("session", null);
    expect(await community.syncData()).toBe(false);
    expect(calls).toHaveLength(0);
  });
});

describe("session invalidation", () => {
  it("clears sign-in before sign-out awaits, while sending the captured bearer", async () => {
    stored.set("pet", { xp: 10 });
    const guard = community.sessionGuard();
    const syncing = community.syncData();
    const old = await request(0);
    const signingOut = community.signOut();
    expect(community.signedIn()).toBe(false);
    expect(guard()).toBe(false);
    const deletion = await request(1);
    expect(deletion.init.headers).toMatchObject({ Authorization: "Bearer session-a" });
    old.resolve(response({ data: { pet: { xp: 99 } } }));
    expect(await syncing).toBe(false);
    expect(stored.get("pet")).toEqual({ xp: 10 });
    deletion.resolve(response(null));
    await signingOut;
  });

  it.each([200, 401])("ignores an old progress response with status %i after a new sign-in", async (status) => {
    const syncing = community.syncData();
    const settled = status === 401 ? expect(syncing).rejects.toThrow() : expect(syncing).resolves.toBe(false);
    const old = await request(0);
    await signInAs("session-b");
    stored.set("pet", { xp: 20 });
    old.resolve(response(status === 401 ? { error: "Expired" } : { data: { pet: { xp: 99 } } }, status));
    await settled;
    expect(stored.get("session")).toBe("session-b");
    expect(stored.get("pet")).toEqual({ xp: 20 });
  });

  it("does not let old runner cleanup clear newer in-flight sync work", async () => {
    const oldSync = community.syncData();
    const old = await request(0);
    stored.set("nonce", "test-nonce");
    window.location.hash = "#id_token=test-id-token";
    const signing = community.finishSignIn();
    (await request(1)).resolve(response(profile("session-b")));
    const current = await request(2);
    old.resolve(response({ data: {} }));
    expect(await oldSync).toBe(false);
    const joined = community.syncData();
    expect(calls).toHaveLength(3);
    current.resolve(response(body(current)));
    const followup = await request(3);
    followup.resolve(response(body(followup)));
    expect(await joined).toBe(true);
    expect(await signing).not.toBeNull();
    expect(calls).toHaveLength(4);
  });

  it("does not let sign-out completion clear a replacement sign-in", async () => {
    const signingOut = community.signOut();
    const old = await request(0);
    await signInAs("session-b");
    old.resolve(response(null));
    await signingOut;
    expect(stored.get("session")).toBe("session-b");
  });

  it("does not install a sign-in exchange superseded by sign-out", async () => {
    stored.set("nonce", "test-nonce");
    window.location.hash = "#id_token=test-id-token";
    const signing = community.finishSignIn();
    const exchange = await request(0);
    const signingOut = community.signOut();
    (await request(1)).resolve(response(null));
    await signingOut;
    exchange.resolve(response(profile("session-b")));
    expect(await signing).toBeNull();
    expect(community.signedIn()).toBe(false);
    expect(calls).toHaveLength(2);
  });

  it("suspends sync before deletion awaits and discards preceding progress", async () => {
    stored.set("pet", { xp: 10 });
    const guard = community.sessionGuard();
    const syncing = community.syncData();
    const old = await request(0);
    const deleting = community.deleteAccount();
    const deletion = await request(1);
    expect(community.signedIn()).toBe(true);
    expect(guard()).toBe(false);
    expect(community.sessionGuard()()).toBe(false);
    expect(await community.syncData()).toBe(false);
    old.resolve(response({ data: { pet: { xp: 99 } } }));
    expect(await syncing).toBe(false);
    expect(stored.get("pet")).toEqual({ xp: 10 });
    deletion.resolve(response(null));
    await deleting;
    expect(community.signedIn()).toBe(false);
  });

  it("retains authentication after failed deletion without reviving previous guards", async () => {
    const guard = community.sessionGuard();
    const deleting = community.deleteAccount();
    const failed = expect(deleting).rejects.toThrow();
    (await request(0)).reject(new TypeError("Connection lost"));
    await failed;
    expect(stored.get("session")).toBe("session-a");
    expect(guard()).toBe(false);
    expect(community.sessionGuard()()).toBe(true);
    const syncing = community.syncData();
    const current = await request(1);
    current.resolve(response(body(current)));
    expect(await syncing).toBe(true);
  });

  it("does not let deletion completion clear a newer sign-in", async () => {
    const deleting = community.deleteAccount();
    const old = await request(0);
    await signInAs("session-b");
    old.resolve(response(null));
    await deleting;
    expect(stored.get("session")).toBe("session-b");
    expect(community.sessionGuard()()).toBe(true);
  });

  it("expires the current session on a current 401", async () => {
    const syncing = community.syncData();
    const expired = expect(syncing).rejects.toThrow();
    (await request(0)).resolve(response({ error: "Expired" }, 401));
    await expired;
    expect(community.signedIn()).toBe(false);
  });
});
