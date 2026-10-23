import { ApiError, type Label, type Queue } from "./community";
import type { SwipeRecord } from "./records";

export type SwipeHistory = ReturnType<typeof SwipeRecord.parse>;
export type SwipeIntent = Readonly<{
  site: string;
  answer: Label;
  kind?: string;
  sessionGuard: () => boolean;
}>;

type FailureAction = "retry" | "refresh";
type Completion = "saved" | "conflict";

export interface SwipeRequestHooks {
  site: string;
  current: () => boolean;
  sessionGuard: () => () => boolean;
  request: (intent: SwipeIntent) => Promise<Queue>;
  refresh: () => Promise<Queue>;
  history: () => SwipeHistory;
  record: (history: SwipeHistory) => void;
  now: () => string;
  recorded: () => void;
  complete: (queue: Queue, result: Completion) => void;
  failed: (error: unknown, action: FailureAction) => void;
  conflict: () => void;
}

export function swipeRequest(hooks: SwipeRequestHooks): {
  canChoose: () => boolean;
  choose: (answer: Label) => { active: () => boolean; submit: (kind?: string) => Promise<void> } | null;
  retry: () => Promise<void>;
  refresh: () => Promise<void>;
} {
  let selectedSession: (() => boolean) | null = null;
  let pending: SwipeIntent | null = null;
  let inFlight = false;
  let phase: "choose" | "selected" | "retry" | "refresh" | "done" = "choose";

  const current = (): boolean => hooks.current() && selectedSession !== null && selectedSession();
  const canChoose = (): boolean => phase === "choose" && hooks.current();

  const refresh = async (): Promise<void> => {
    if (phase !== "refresh" || inFlight || !current()) return;
    inFlight = true;
    try {
      const queue = await hooks.refresh();
      if (!current()) return;
      phase = "done";
      hooks.complete(queue, "conflict");
    } catch (error) {
      if (current()) hooks.failed(error, "refresh");
    } finally {
      inFlight = false;
    }
  };

  const attempt = async (): Promise<void> => {
    const intent = pending;
    if (!intent || phase !== "retry" || inFlight || !current()) return;
    inFlight = true;
    let conflict = false;
    try {
      const queue = await hooks.request(intent);
      if (!current()) return;
      const mine = hooks.history();
      if (!current()) return;
      if (!Object.hasOwn(mine, intent.site)) {
        const at = hooks.now();
        if (!current()) return;
        hooks.record({ ...mine, [intent.site]: { a: intent.answer, at } });
        if (!current()) return;
        hooks.recorded();
      }
      if (!current()) return;
      phase = "done";
      hooks.complete(queue, "saved");
    } catch (error) {
      if (!current()) return;
      if (error instanceof ApiError && error.status === 409) {
        phase = "refresh";
        conflict = true;
        hooks.conflict();
      } else {
        hooks.failed(error, "retry");
      }
    } finally {
      inFlight = false;
    }
    if (conflict) await refresh();
  };

  return {
    canChoose,
    choose(answer) {
      if (!canChoose()) return null;
      const sessionGuard = hooks.sessionGuard();
      if (!sessionGuard()) return null;
      selectedSession = sessionGuard;
      phase = "selected";
      const active = (): boolean => phase === "selected" && current();
      return {
        active,
        async submit(kind) {
          if (!active()) return;
          pending = Object.freeze({ site: hooks.site, answer, ...(kind === undefined ? {} : { kind }), sessionGuard });
          phase = "retry";
          await attempt();
        },
      };
    },
    retry: attempt,
    refresh,
  };
}
