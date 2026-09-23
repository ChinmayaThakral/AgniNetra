"""Phase 5 acceptance: the diurnal profile the polar orbiting record cannot see.

The polar record carries zero detections at 17:00 IST across both burning seasons,
which is a statement about the instrument. This asks the other question: what was
burning then. A geostationary record samples every half hour, so the hours the polar
constellation never visits are ordinary hours in it.

Reports coverage before any fraction, because a diurnal histogram built from a
partial day understates exactly the hours that are missing, and that is the number
this figure exists to produce.

Writes docs/figures/insat_diurnal<window>.png and docs/insat_diurnal<window>.md,
where <window> is empty for the default source and _<name> otherwise.
"""

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

from ml.documents import provenance_line
from ml.paths import ARTIFACT_DIR, DATA_DIR, FIGURE_DIR, ROOT, ensure_dir

# The hours the polar constellation actually visits, measured in this project from
# 344227 detections on the three sensors present in both burning seasons.
POLAR_HOURS: tuple[int, ...] = (1, 2, 13, 14)
# The window the published shift moved into, where the polar record has none.
EVENING_START, EVENING_END = 15, 20


def _suffix(source: str) -> str:
    """Output names carry the window when it is not the default one.

    Both scripts wrote fixed filenames. Running either on a second season would have
    replaced the first season's figure and table in place, under the names the paper
    outline cites, with nothing in the output saying so.
    """
    return "" if source == "insat" else f"_{source.removeprefix('insat_')}"


def _source_name() -> str:
    """Which derived subdirectory to read, so one season cannot be read as another."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", default="insat", help="subdirectory under data/derived")
    return str(parser.parse_args().source)


def main() -> int:
    name = _source_name()
    window_tag = _suffix(name)
    source = DATA_DIR / "derived" / name
    files = sorted(source.glob("*.npz"))
    if not files:
        print(f"BLOCKED: no reduced granules in {source}", file=sys.stderr)
        return 2

    per_slot: dict[tuple[int, int], list[int]] = defaultdict(list)
    per_hour: dict[int, list[int]] = defaultdict(list)
    days: set[str] = set()
    for path in files:
        with np.load(path, allow_pickle=False) as data:
            hour = int(data["hour_ist"])
            minute = int(data["minute_ist"])
            count = int(data["longitude"].size)
            stamp = str(data["acquired_utc"])[:10]
        per_slot[(hour, minute)].append(count)
        per_hour[hour].append(count)
        days.add(stamp)

    slots_expected = 48
    coverage = len(per_slot) / slots_expected
    print(f"granules reduced: {len(files)} over {len(days)} day(s)")
    print(f"half hour slots present: {len(per_slot)} of {slots_expected}, {coverage:.0%}")

    hours = np.arange(24)
    mean_by_hour = np.array([np.mean(per_hour[h]) if h in per_hour else np.nan for h in hours])
    observed = ~np.isnan(mean_by_hour)

    total = np.nansum(mean_by_hour)
    evening_mask = (hours >= EVENING_START) & (hours < EVENING_END) & observed
    polar_mask = np.isin(hours, POLAR_HOURS) & observed
    evening = float(np.nansum(mean_by_hour[evening_mask]))
    polar = float(np.nansum(mean_by_hour[polar_mask]))

    complete = bool(observed.all())
    print(f"\nhours observed: {int(observed.sum())} of 24")
    if not complete:
        print("PARTIAL. The fractions below are lower bounds on a full day.")
    print(f"mean detections per granule, summed over observed hours: {total:.1f}")
    print(f"  in the evening window {EVENING_START} to {EVENING_END} IST: {evening:.1f}")
    print(f"  in the polar overpass hours {POLAR_HOURS}: {polar:.1f}")
    if total > 0:
        print(f"  evening share of observed activity: {evening / total:.1%}")
        print(f"  polar overpass share:               {polar / total:.1%}")

    fig, ax = plt.subplots(figsize=(9, 4.2))
    bars = ax.bar(hours[observed], mean_by_hour[observed], color="#444", width=0.82)
    for h, bar in zip(hours[observed], bars, strict=True):
        if EVENING_START <= h < EVENING_END:
            bar.set_color("#b00020")
        elif h in POLAR_HOURS:
            bar.set_color("#1f6feb")
    ax.set_xlabel("hour, IST")
    ax.set_ylabel("mean INSAT-3DS detections per granule")
    ax.set_xticks(range(0, 24, 2))
    # One line does not fit a 9 inch canvas and tight_layout cannot wrap a title, so
    # the colour legend goes on a second line. A newline in the title stacks the two
    # properly; a separate text call at the same height just overlaps it.
    ax.set_title(
        f"Diurnal activity over India, INSAT-3DS, {len(days)} day(s)\n"
        f"red is the window the polar record never sees, blue is its overpass hours",
        fontsize=11,
    )
    if not complete:
        ax.text(
            0.99,
            0.95,
            f"partial: {int(observed.sum())} of 24 hours",
            transform=ax.transAxes,
            ha="right",
            va="top",
            fontsize=8,
            color="#b00020",
        )
    fig.tight_layout()
    ensure_dir(FIGURE_DIR)
    fig.savefig(FIGURE_DIR / f"insat_diurnal{window_tag}.png", dpi=150)
    plt.close(fig)

    payload = {
        "granules": len(files),
        "days": sorted(days),
        "slots_present": len(per_slot),
        "slots_expected": slots_expected,
        "hours_observed": int(observed.sum()),
        "complete_day": complete,
        "mean_by_hour": {
            int(h): (None if np.isnan(v) else float(v))
            for h, v in zip(hours, mean_by_hour, strict=True)
        },
        "evening_share": (evening / total) if total > 0 else None,
        "polar_overpass_share": (polar / total) if total > 0 else None,
    }
    ensure_dir(ARTIFACT_DIR).joinpath(f"insat_diurnal{window_tag}.json").write_text(
        json.dumps(payload, indent=2, allow_nan=False)
    )

    lines = [
        "# Diurnal activity from INSAT-3DS, and what the polar record misses",
        "",
        f"Regenerate: `uv run python {Path('scripts/diurnal_profile.py')}`",
        provenance_line(__file__),
        "",
        f"{len(files)} granules over {len(days)} day(s), "
        f"{len(per_slot)} of {slots_expected} half hour slots.",
        "",
    ]
    if not complete:
        lines += [
            f"**Partial: {int(observed.sum())} of 24 hours observed.** Every fraction "
            "below is a lower bound, and an absent hour reads as no activity rather "
            "than as no observation, which is the same censoring this figure exists "
            "to measure. Do not quote these as the result until the day is complete.",
            "",
        ]
    lines += ["| Hour IST | Mean detections per granule | Polar record |", "|---|---|---|"]
    for h in hours:
        if not observed[h]:
            lines.append(f"| {h:02d} | not observed | |")
            continue
        tag = (
            "overpass"
            if h in POLAR_HOURS
            else ("**never visits**" if EVENING_START <= h < EVENING_END else "")
        )
        lines.append(f"| {h:02d} | {mean_by_hour[h]:.1f} | {tag} |")
    lines.append("")
    (ROOT / "docs" / f"insat_diurnal{window_tag}.md").write_text("\n".join(lines))
    print(
        f"\nwrote docs/figures/insat_diurnal{window_tag}.png and docs/insat_diurnal{window_tag}.md"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
