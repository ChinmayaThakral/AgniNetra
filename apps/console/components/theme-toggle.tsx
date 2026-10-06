"use client";

import { useEffect, useState } from "react";

// Light or dark. The choice lives in the address, ?theme=dark, like every other piece of
// console state, so a shared link opens the way it was seen and nothing is stored.

type Theme = "light" | "dark";

function initial(): Theme {
  const asked = new URLSearchParams(window.location.search).get("theme");
  if (asked === "light" || asked === "dark") return asked;
  return window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
}

export function ThemeToggle() {
  const [theme, setTheme] = useState<Theme | null>(null);

  useEffect(() => {
    // The theme is only knowable in the browser, so it is read once after mounting.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setTheme(initial());
  }, []);

  useEffect(() => {
    if (!theme) return;
    document.documentElement.dataset.theme = theme;
  }, [theme]);

  if (!theme) return <button className="theme-toggle" disabled type="button">Theme</button>;
  const next: Theme = theme === "dark" ? "light" : "dark";
  return (
    <button
      aria-label={`Switch to the ${next} theme`}
      className="theme-toggle"
      onClick={() => {
        const url = new URL(window.location.href);
        url.searchParams.set("theme", next);
        window.history.replaceState(null, "", url);
        setTheme(next);
      }}
      type="button"
    >
      {theme === "dark" ? "Light" : "Dark"}
    </button>
  );
}
