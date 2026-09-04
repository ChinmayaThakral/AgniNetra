/**
 * Formatting helpers. A value the pipeline did not measure renders as the words
 * "not measured" rather than as a dash, a zero, or a hidden element.
 */

export const NOT_MEASURED = "not measured";

export function metres(value: number | null): string {
  if (value === null) return NOT_MEASURED;
  return value >= 1000 ? `${(value / 1000).toFixed(2)} km` : `${Math.round(value)} m`;
}

export function power(value: number | null): string {
  return value === null ? NOT_MEASURED : `${value.toFixed(1)} MW`;
}

export function fraction(value: number | null, digits = 3): string {
  return value === null ? NOT_MEASURED : value.toFixed(digits);
}

export function percent(value: number | null, digits = 2): string {
  return value === null ? NOT_MEASURED : `${(value * 100).toFixed(digits)} %`;
}

export function days(value: number | null): string {
  return value === null ? NOT_MEASURED : `${value.toFixed(2)} d`;
}

export const CLASS_COLOUR: Record<string, string> = {
  flare: "#b00020",
  industrial: "#c46210",
  agricultural: "#3f7f4f",
};

export function classColour(name: string): string {
  return CLASS_COLOUR[name] ?? "#2b6cb0";
}

/**
 * Counts are grouped in the Indian convention, lakh and crore, and the locale is
 * pinned rather than left to the viewer's machine. An unpinned toLocaleString
 * renders 601941 as "6,01,941" on a machine set to en-IN and "601,941" elsewhere,
 * so the same build would show a different number to different readers. The
 * project's rule is that a displayed number has one source and one form.
 */
export function count(value: number): string {
  return value.toLocaleString("en-IN");
}
