import { describe, expect, it, vi } from "vitest";
import { ApiError, type Label, Queue } from "./community";
import { swipeRequest, type SwipeHistory, type SwipeIntent, type SwipeRequestHooks } from "./swipe-request";

const SITE = "s0123456789";
const OTHER = "sabcdef0123";
const NOW = "2026-10-23T12:00:00.000Z";
const BEFORE = "2026-10-22T12:00:00.000Z";
const NEXT = Queue.parse({
  item: { id: OTHER, chip: `chips/${OTHER}.webp`, acquired: "2026-10-01" },
  kinds: ["coal mine", "power plant"],
  answered: 1,
  total: 2,
});
const FINISHED = Queue.parse({ item: null, answered: 2, total: 2 });

function deferred<T>(): {
  promise: Promise<T>;
  resolve: (value: T) => void;
  reject: (reason: unknown) => void;
} {
  let resolve: (value: T) => void = () => { throw new Error("Promise not initialized."); };
  let reject: (reason: unknown) => void = () => { throw new Error("Promise not initialized."); };
  const promise = new Promise<T>((yes, no) => { resolve = yes; reject = no; });
  return { promise, resolve, reject };
}

function harness(initial: SwipeHistory = {}) {
  const state = { current: true, signedIn: true, generation: 0, deleting: false };
  let saved = initial;
  const request = vi.fn<SwipeRequestHooks["request"]>().mockResolvedValue(NEXT);
  const refresh = vi.fn<SwipeRequestHooks["refresh"]>().mockResolvedValue(NEXT);
  const history = vi.fn(() => saved);
  const record = vi.fn((value: SwipeHistory) => { saved = value; });
  const now = vi.fn(() => NOW);
  const recorded = vi.fn<SwipeRequestHooks["recorded"]>();
  const complete = vi.fn<SwipeRequestHooks["complete"]>();
  const failed = vi.fn<SwipeRequestHooks["failed"]>();
  const conflict = vi.fn<SwipeRequestHooks["conflict"]>();
  const coordinator = swipeRequest({
    site: SITE,
    current: () => state.current,
    sessionGuard: () => {
      const generation = state.generation;
      const active = state.signedIn && !state.deleting;
      return () => active && state.signedIn && !state.deleting && state.generation === generation;
    },
    request, refresh, history, record, now, recorded, complete, failed, conflict,
  });
  return {
    coordinator, state, request, refresh, history, record, now, recorded, complete, failed, conflict,
    choose(answer: Label) {
      const selection = coordinator.choose(answer);
      if (!selection) throw new Error("Choice was not available.");
      return selection;
    },
    replaceHistory(value: SwipeHistory) { saved = value; },
    snapshot: () => saved,
  };
}

const INTENTS: { answer: Label; kind?: string }[] = [
  { answer: "industry" },
  { answer: "industry", kind: "coal mine" },
  { answer: "not industry" },
  { answer: "unsure" },
];

const INVALIDATIONS: [string, (state: ReturnType<typeof harness>["state"]) => void][] = [
  ["replaced card", (state) => { state.current = false; }],
  ["signed-out session", (state) => { state.signedIn = false; }],
  ["replacement account", (state) => { state.generation += 1; }],
  ["pending deletion", (state) => { state.deleting = true; }],
];

describe("Swipe fixed-intent requests", () => {
  it.each(INTENTS)("recovers a discarded success for $answer, kind $kind", async ({ answer, kind }) => {
    const h = harness();
    let serverSaved: SwipeIntent | undefined;
    h.request.mockImplementationOnce(async (intent) => {
      serverSaved = intent;
      throw new TypeError("Response lost after saving.");
    });
    h.request.mockImplementationOnce(async (intent) => {
      expect(intent).toBe(serverSaved);
      return NEXT;
    });
    const selection = h.choose(answer);
    await selection.submit(kind);

    expect(h.record).not.toHaveBeenCalled();
    expect(h.recorded).not.toHaveBeenCalled();
    expect(h.failed).toHaveBeenCalledWith(expect.any(TypeError), "retry");
    expect(h.coordinator.choose("unsure")).toBeNull();
    expect(h.coordinator.canChoose()).toBe(false);
    expect(selection.active()).toBe(false);
    await selection.submit(kind === undefined ? "power plant" : undefined);
    expect(h.request).toHaveBeenCalledTimes(1);

    await h.coordinator.retry();
    expect(h.request).toHaveBeenCalledTimes(2);
    const intent = h.request.mock.calls[0]?.[0];
    expect(intent).toMatchObject({ site: SITE, answer, ...(kind === undefined ? {} : { kind }) });
    expect(Object.isFrozen(intent)).toBe(true);
    expect(h.record).toHaveBeenCalledTimes(1);
    expect(h.snapshot()).toEqual({ [SITE]: { a: answer, at: NOW } });
    expect(h.now).toHaveBeenCalledTimes(1);
    expect(h.recorded).toHaveBeenCalledTimes(1);
    expect(h.complete).toHaveBeenCalledExactlyOnceWith(NEXT, "saved");
    await h.coordinator.retry();
    await h.coordinator.refresh();
    expect(h.request).toHaveBeenCalledTimes(2);
    expect(h.recorded).toHaveBeenCalledTimes(1);
  });

  it("allows only one kind submission and one in-flight attempt", async () => {
    const h = harness();
    const response = deferred<Queue>();
    h.request.mockReturnValueOnce(response.promise);
    const selection = h.choose("industry");
    const saving = selection.submit("coal mine");
    await selection.submit("power plant");
    await selection.submit();
    await h.coordinator.retry();
    await h.coordinator.refresh();
    expect(h.coordinator.choose("not industry")).toBeNull();
    expect(h.request).toHaveBeenCalledTimes(1);
    expect(h.request.mock.calls[0]?.[0].kind).toBe("coal mine");
    response.resolve(NEXT);
    await saving;
    expect(h.recorded).toHaveBeenCalledTimes(1);
  });

  it.each([
    ["network", new TypeError("Connection closed.")],
    ["server", new ApiError(503, "Unavailable.")],
    ["JSON", new SyntaxError("Incomplete JSON.")],
  ])("keeps the same answer and kind after a %s failure", async (_name, error) => {
    const h = harness();
    h.request.mockRejectedValueOnce(error);
    const selection = h.choose("industry");
    await selection.submit("coal mine");
    expect(h.failed).toHaveBeenCalledWith(error, "retry");
    expect(h.coordinator.choose("not industry")).toBeNull();
    await selection.submit("power plant");
    await h.coordinator.retry();
    expect(h.request.mock.calls[1]?.[0]).toBe(h.request.mock.calls[0]?.[0]);
    expect(h.request.mock.calls[1]?.[0].kind).toBe("coal mine");
    expect(h.recorded).toHaveBeenCalledTimes(1);
  });

  it("does not finalize a malformed successful response until exact retry parses", async () => {
    const h = harness();
    h.request.mockImplementationOnce(async () => Queue.parse({ item: { id: "invalid" } }));
    await h.choose("unsure").submit();
    expect(h.failed).toHaveBeenCalledWith(expect.any(Error), "retry");
    expect(h.complete).not.toHaveBeenCalled();
    expect(h.history).not.toHaveBeenCalled();
    await h.coordinator.retry();
    expect(h.request.mock.calls[1]?.[0]).toBe(h.request.mock.calls[0]?.[0]);
    expect(h.complete).toHaveBeenCalledExactlyOnceWith(NEXT, "saved");
  });

  it("re-reads history after success and preserves existing entries and timestamps", async () => {
    const h = harness();
    const response = deferred<Queue>();
    h.request.mockReturnValueOnce(response.promise);
    const saving = h.choose("industry").submit("coal mine");
    const synced: SwipeHistory = {
      [SITE]: { a: "factory", at: BEFORE },
      [OTHER]: { a: "not industry", at: BEFORE },
    };
    h.replaceHistory(synced);
    response.resolve(NEXT);
    await saving;
    expect(h.history).toHaveBeenCalledTimes(1);
    expect(h.snapshot()).toBe(synced);
    expect(h.record).not.toHaveBeenCalled();
    expect(h.now).not.toHaveBeenCalled();
    expect(h.recorded).not.toHaveBeenCalled();
    expect(h.complete).toHaveBeenCalledExactlyOnceWith(NEXT, "saved");
  });

  it("adds only the absent site and can finish the queue", async () => {
    const h = harness({ [OTHER]: { a: "flare", at: BEFORE } });
    h.request.mockResolvedValueOnce(FINISHED);
    await h.choose("not industry").submit();
    expect(h.snapshot()).toEqual({
      [OTHER]: { a: "flare", at: BEFORE },
      [SITE]: { a: "not industry", at: NOW },
    });
    expect(h.complete).toHaveBeenCalledExactlyOnceWith(FINISHED, "saved");
  });

  it("explains a conflicting saved answer and refreshes without local history or XP", async () => {
    const h = harness();
    h.request.mockRejectedValueOnce(new ApiError(409, "Already answered."));
    await h.choose("industry").submit("power plant");
    expect(h.conflict).toHaveBeenCalledTimes(1);
    expect(h.refresh).toHaveBeenCalledTimes(1);
    expect(h.complete).toHaveBeenCalledExactlyOnceWith(NEXT, "conflict");
    expect(h.history).not.toHaveBeenCalled();
    expect(h.record).not.toHaveBeenCalled();
    expect(h.recorded).not.toHaveBeenCalled();
    await h.coordinator.retry();
    expect(h.request).toHaveBeenCalledTimes(1);
  });

  it("retries only the queue refresh if fetching after a conflict fails", async () => {
    const h = harness();
    const error = new TypeError("Queue response lost.");
    h.request.mockRejectedValueOnce(new ApiError(409, "Already answered."));
    h.refresh.mockRejectedValueOnce(error);
    await h.choose("unsure").submit();
    expect(h.failed).toHaveBeenCalledWith(error, "refresh");
    expect(h.complete).not.toHaveBeenCalled();
    expect(h.coordinator.choose("industry")).toBeNull();
    await h.coordinator.retry();
    expect(h.request).toHaveBeenCalledTimes(1);
    const response = deferred<Queue>();
    h.refresh.mockReturnValueOnce(response.promise);
    const refreshing = h.coordinator.refresh();
    await h.coordinator.refresh();
    expect(h.refresh).toHaveBeenCalledTimes(2);
    response.resolve(FINISHED);
    await refreshing;
    expect(h.complete).toHaveBeenCalledExactlyOnceWith(FINISHED, "conflict");
    expect(h.recorded).not.toHaveBeenCalled();
  });

  it.each(INVALIDATIONS)("ignores an old animation or kind pick after %s", async (_name, invalidate) => {
    const h = harness();
    const selection = h.choose("industry");
    invalidate(h.state);
    expect(selection.active()).toBe(false);
    await selection.submit("coal mine");
    await h.coordinator.retry();
    expect(h.request).not.toHaveBeenCalled();
    expect(h.record).not.toHaveBeenCalled();
    expect(h.complete).not.toHaveBeenCalled();
  });

  it.each(INVALIDATIONS)("ignores a successful old attempt after %s", async (_name, invalidate) => {
    const h = harness();
    const response = deferred<Queue>();
    h.request.mockReturnValueOnce(response.promise);
    const saving = h.choose("industry").submit("coal mine");
    invalidate(h.state);
    response.resolve(NEXT);
    await saving;
    expect(h.history).not.toHaveBeenCalled();
    expect(h.record).not.toHaveBeenCalled();
    expect(h.recorded).not.toHaveBeenCalled();
    expect(h.complete).not.toHaveBeenCalled();
    expect(h.failed).not.toHaveBeenCalled();
  });

  it.each(INVALIDATIONS)("ignores an old rejection and retry after %s", async (_name, invalidate) => {
    const h = harness();
    const response = deferred<Queue>();
    h.request.mockReturnValueOnce(response.promise);
    const saving = h.choose("unsure").submit();
    invalidate(h.state);
    response.reject(new ApiError(409, "Already answered."));
    await saving;
    await h.coordinator.retry();
    expect(h.request).toHaveBeenCalledTimes(1);
    expect(h.conflict).not.toHaveBeenCalled();
    expect(h.refresh).not.toHaveBeenCalled();
    expect(h.failed).not.toHaveBeenCalled();
    expect(h.complete).not.toHaveBeenCalled();
  });

  it.each(INVALIDATIONS)("blocks the retry callback after %s", async (_name, invalidate) => {
    const h = harness();
    h.request.mockRejectedValueOnce(new TypeError("Response lost."));
    await h.choose("industry").submit("coal mine");
    expect(h.failed).toHaveBeenCalledTimes(1);
    invalidate(h.state);
    await h.coordinator.retry();
    expect(h.request).toHaveBeenCalledTimes(1);
    expect(h.recorded).not.toHaveBeenCalled();
    expect(h.complete).not.toHaveBeenCalled();
  });

  it.each(INVALIDATIONS)("ignores an old queue refresh after %s", async (_name, invalidate) => {
    const h = harness();
    const response = deferred<Queue>();
    h.request.mockRejectedValueOnce(new ApiError(409, "Already answered."));
    h.refresh.mockReturnValueOnce(response.promise);
    const saving = h.choose("unsure").submit();
    await Promise.resolve();
    expect(h.refresh).toHaveBeenCalledTimes(1);
    invalidate(h.state);
    response.resolve(NEXT);
    await saving;
    await h.coordinator.refresh();
    expect(h.refresh).toHaveBeenCalledTimes(1);
    expect(h.recorded).not.toHaveBeenCalled();
    expect(h.complete).not.toHaveBeenCalled();
  });

  it("rechecks the session before finalizing freshly read history", async () => {
    const h = harness();
    h.history.mockImplementationOnce(() => {
      h.state.deleting = true;
      return {};
    });
    await h.choose("industry").submit();
    expect(h.record).not.toHaveBeenCalled();
    expect(h.recorded).not.toHaveBeenCalled();
    expect(h.complete).not.toHaveBeenCalled();
  });

  it("refuses to capture an inactive session or an obsolete card", async () => {
    const h = harness();
    h.state.deleting = true;
    expect(h.coordinator.choose("unsure")).toBeNull();
    h.state.deleting = false;
    h.state.signedIn = false;
    expect(h.coordinator.choose("industry")).toBeNull();
    h.state.signedIn = true;
    h.state.current = false;
    expect(h.coordinator.canChoose()).toBe(false);
    expect(h.coordinator.choose("not industry")).toBeNull();
    await h.coordinator.retry();
    expect(h.request).not.toHaveBeenCalled();
  });
});
