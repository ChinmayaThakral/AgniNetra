// Small helpers so every piece of text reaches the page through textContent. Nothing in
// the feed is ever parsed as HTML.

export function el<K extends keyof HTMLElementTagNameMap>(
  tag: K,
  className?: string,
  text?: string,
): HTMLElementTagNameMap[K] {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

// A count and its noun, so one evening never reads "1 evenings".
export function plural(n: number, one: string, many = `${one}s`): string {
  return `${n} ${n === 1 ? one : many}`;
}

export function percent(share: number | null): string {
  return share === null ? "not measured" : `${Math.round(share * 100)}%`;
}

export function howSure(level: "low" | "medium", note?: string): HTMLElement {
  const badge = el("span", `how-sure how-sure-${level}`, `how sure: ${level}`);
  badge.title = note ?? "Weak labels from maps, not checked on the ground. Not an official count.";
  return badge;
}
