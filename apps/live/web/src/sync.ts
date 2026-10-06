import { exportFile, importFile } from "./backup";
import { type Config, config, deleteAccount, me, signedIn, signIn, signOut, syncData } from "./community";
import { el } from "./dom";

// The data button beside the theme switch. It opens one small window: sign in with Google
// to keep progress in step across devices, or carry it by hand as a file. Signed in, the
// app syncs on its own a few seconds after anything changes.

const SYNC_DELAY_MS = 4000;

export function syncButton(): HTMLElement {
  const button = el("button", "icon-button sync-button");
  button.type = "button";
  const dialog = el("dialog", "sync-dialog");
  dialog.setAttribute("aria-label", "Your data");
  let settings: Config | null = null;
  let pending: number | undefined;
  let lastSync: string | null = null;

  const paint = (): void => {
    button.textContent = signedIn() ? "Synced" : "Your data";
    button.classList.toggle("on", signedIn());
  };

  const sync = (): Promise<void> =>
    syncData()
      .then(() => {
        lastSync = new Date().toLocaleTimeString("en-IN", { hour: "2-digit", minute: "2-digit" });
      })
      .catch(() => undefined)
      .finally(paint);

  const schedule = (): void => {
    if (!signedIn()) return;
    if (pending !== undefined) window.clearTimeout(pending);
    pending = window.setTimeout(() => void sync(), SYNC_DELAY_MS);
  };
  window.addEventListener("netu-xp", schedule);
  window.addEventListener("agninetra-data", schedule);

  const render = async (): Promise<void> => {
    const body: HTMLElement[] = [el("h2", "", "Your data")];
    body.push(el("p", "muted small", "Your Heatle streak, your Netu and your qualifying progress. Keep them in step across devices with Google, or carry them yourself as a file."));
    const account = el("section", "sync-section");
    account.append(el("h3", "", "Sync with Google"));
    settings ??= await config();
    if (!settings) {
      account.append(el("p", "small muted", "Sync is not switched on for this server yet. Use a file below."));
    } else if (!signedIn()) {
      account.append(el("p", "small", "Sign in once and your progress follows you. Signing in also opens community labelling in Swipe, once you qualify. Only your email address is kept, never your name or contacts."));
      const go = el("button", "button primary", "Sign in with Google");
      const clientId = settings.client_id;
      go.addEventListener("click", () => signIn(clientId));
      account.append(go);
    } else {
      const profile = await me().catch(() => null);
      account.append(el("p", "small", profile ? `Signed in as ${profile.email}.` : "Signed in."));
      if (lastSync) account.append(el("p", "small muted", `Last synced at ${lastSync}.`));
      const row = el("div", "choices");
      const now = el("button", "button", "Sync now");
      now.addEventListener("click", () => void sync().then(render));
      const out = el("button", "button", "Sign out");
      out.addEventListener("click", () => void signOut().then(() => window.location.reload()));
      const remove = el("button", "button danger", "Delete my account");
      remove.addEventListener("click", () => {
        if (remove.dataset.armed !== "yes") {
          remove.dataset.armed = "yes";
          remove.textContent = "Tap again to delete everything";
          return;
        }
        void deleteAccount().then(() => window.location.reload());
      });
      row.append(now, out, remove);
      account.append(row);
    }
    body.push(account);

    const files = el("section", "sync-section");
    files.append(el("h3", "", "Move it as a file"), el("p", "small muted", "Export here and import on the other device. The file never reaches our server."));
    const row = el("div", "choices");
    const save = el("button", "button", "Export");
    save.addEventListener("click", () => {
      const url = URL.createObjectURL(exportFile());
      const link = el("a", "");
      link.href = url;
      link.download = `agninetra-my-data-${new Date().toISOString().slice(0, 10)}.json`;
      link.click();
      window.setTimeout(() => URL.revokeObjectURL(url), 60_000);
    });
    const picker = el("input", "");
    picker.type = "file";
    picker.accept = "application/json,.json";
    picker.hidden = true;
    const status = el("p", "small", "");
    picker.addEventListener("change", () => {
      const file = picker.files?.[0];
      if (!file) return;
      importFile(file)
        .then(() => {
          status.textContent = "Imported. Reloading with your data.";
          window.dispatchEvent(new Event("agninetra-data"));
          window.setTimeout(() => window.location.reload(), 900);
        })
        .catch((error: unknown) => {
          status.textContent = error instanceof Error ? error.message : "That file could not be read.";
        });
    });
    const load = el("button", "button", "Import");
    load.addEventListener("click", () => picker.click());
    row.append(save, load, picker);
    files.append(row, status);
    body.push(files);

    const close = el("button", "icon-button dialog-close", "Close");
    close.addEventListener("click", () => dialog.close());
    const privacy = el("a", "small", "What is kept, and how to remove it");
    privacy.href = "privacy.html";
    body.push(privacy, close);
    dialog.replaceChildren(...body);
  };

  button.addEventListener("click", () => {
    dialog.replaceChildren(el("p", "small muted", "Loading."));
    dialog.showModal();
    void render();
  });
  dialog.addEventListener("click", (event) => {
    if (event.target === dialog) dialog.close();
  });
  paint();
  if (signedIn()) void sync();
  const wrap = el("span", "sync-wrap");
  wrap.append(button, dialog);
  return wrap;
}
