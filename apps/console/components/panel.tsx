"use client";

import { useEffect, useState, type ReactNode } from "react";

// One window of the console's side column. It can be minimised to its title, or
// maximised over the whole workspace and closed again with the button or Escape.

function Icon({ path }: { path: string }) {
  return (
    <svg aria-hidden="true" fill="none" height="14" stroke="currentColor" strokeLinecap="round" strokeWidth="2" viewBox="0 0 24 24" width="14">
      <path d={path} />
    </svg>
  );
}

const MINIMISE = "M5 12h14";
const RESTORE_BODY = "M12 5v14M5 12h14";
const MAXIMISE = "M4 9V4h5M20 9V4h-5M4 15v5h5M20 15v5h-5";
const SHRINK = "M9 4v5H4M15 4v5h5M9 20v-5H4M15 20v-5h5";

export function Panel({
  title,
  children,
  flat = false,
  startOpen = true,
}: {
  title: string;
  children: ReactNode;
  flat?: boolean;
  startOpen?: boolean;
}) {
  const [open, setOpen] = useState(startOpen);
  const [max, setMax] = useState(false);

  useEffect(() => {
    if (!max) return;
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") setMax(false);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [max]);

  const classes = ["panel", max ? "max" : "", flat ? "flat" : ""].filter(Boolean).join(" ");
  return (
    <>
      {max ? <div className="panel-backdrop" onClick={() => setMax(false)} /> : null}
      <section aria-label={title} className={classes}>
        <header className="panel-head">
          <h2>{title}</h2>
          <div className="panel-tools">
            {max ? null : (
              <button
                aria-expanded={open}
                aria-label={open ? `Minimise ${title}` : `Show ${title}`}
                onClick={() => setOpen(!open)}
                title={open ? "Minimise" : "Show"}
                type="button"
              >
                <Icon path={open ? MINIMISE : RESTORE_BODY} />
              </button>
            )}
            <button
              aria-label={max ? `Restore ${title}` : `Maximise ${title}`}
              onClick={() => {
                setMax(!max);
                setOpen(true);
              }}
              title={max ? "Restore (Esc)" : "Maximise"}
              type="button"
            >
              <Icon path={max ? SHRINK : MAXIMISE} />
            </button>
          </div>
        </header>
        {open || max ? <div className="panel-body">{children}</div> : null}
      </section>
    </>
  );
}
