"""The daily social kit: Netu images, a caption and stickers, ready for the owner to post.

Everything is made from the evening's feed, which has already passed validation, and
written to `data/live_social/<date>/`, which git never tracks. Nothing is posted: the
owner posts by hand from their own accounts. Every image carries the how sure note and
"not an official count", and every caption is a fixed template filled from the feed,
the same rule Netu follows in the app.

Usage:
    uv run python -m apps.live.pipeline.social_kit
    uv run python -m apps.live.pipeline.social_kit --feed apps/live/web/public/feed/2026-09-25.json
"""

import argparse
import json
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
from matplotlib.patches import Circle, PathPatch
from matplotlib.path import Path as MplPath
from PIL import Image

from ml.paths import DATA_DIR, ROOT

FEED = ROOT / "apps" / "live" / "web" / "public" / "feed" / "latest.json"
OUT = DATA_DIR / "live_social"
GROUND = "#07090d"
EMBER = "#ffb020"
POLAR = "#9ec5ff"
TEXT = "#e8edf5"
MUTED = "#8b95a6"
SURE = "#ffcf70"

# Netu's outline, the same curve as the app's icon, in a 100 by 120 box with y down.
FLAME = [
    (MplPath.MOVETO, (50, 4)),
    (MplPath.CURVE4, (62, 30)),
    (MplPath.CURVE4, (88, 44)),
    (MplPath.CURVE4, (84, 78)),
    (MplPath.CURVE4, (81, 104)),
    (MplPath.CURVE4, (64, 116)),
    (MplPath.CURVE4, (50, 116)),
    (MplPath.CURVE4, (36, 116)),
    (MplPath.CURVE4, (19, 104)),
    (MplPath.CURVE4, (16, 78)),
    (MplPath.CURVE4, (13, 52)),
    (MplPath.CURVE4, (34, 42)),
    (MplPath.CURVE4, (38, 20)),
    (MplPath.CURVE4, (44, 32)),
    (MplPath.CURVE4, (50, 30)),
    (MplPath.CURVE4, (50, 4)),
    (MplPath.CLOSEPOLY, (50, 4)),
]

CAPTIONS = {
    "match": (
        "Evening Match, {day}. Polar satellites caught {polar} of today's fire cells and "
        "were all out by {polar_last}. INSAT-3DS caught {insat}. The satellites clock out; "
        "the smoke does not."
    ),
    "quiet": "Evening Match, {day}. A quiet sky over India today. Netu is resting its eye.",
    "tomorrow": "Tomorrow in {city}: PM2.5 forecast about {pm25}, CPCB {category}.",
    "credits": (
        "How sure: low. Weak labels from maps, not an official count. Fires shown per 11 km "
        "cell, never as fields. Data Source MOSDAC/SAC/ISRO. NASA FIRMS. CAMS via Open-Meteo. "
        "Boundaries (c) OpenStreetMap contributors, ODbL."
    ),
}


def pct(share: float | None) -> str:
    return "not measured" if share is None else f"{round(100 * share)} percent"


def mood(feed: dict) -> str:
    said = {line["template"] for line in feed["netu"]}
    if "worried" in said:
        return "worried"
    if "quiet" in said:
        return "resting"
    return "watchful"


def draw_netu(ax, x: float, y: float, size: float, feeling: str) -> None:
    """Netu centred at (x, y) in axes pixels, `size` wide."""
    scale = size / 100

    def at(px: float, py: float) -> tuple[float, float]:
        return (x + (px - 50) * scale, y - (py - 60) * scale)

    codes, points = zip(*FLAME, strict=True)
    ax.add_patch(
        PathPatch(MplPath([at(*p) for p in points], codes), facecolor="#ff8a2b", edgecolor="none")
    )
    if feeling == "resting":
        xs = [at(38 + i, 60 + 8 * (1 - ((i - 12) / 12) ** 2))[0] for i in range(25)]
        ys = [at(38 + i, 60 + 8 * (1 - ((i - 12) / 12) ** 2))[1] for i in range(25)]
        ax.plot(xs, ys, color="#111111", linewidth=size / 25, solid_capstyle="round")
        return
    ax.add_patch(Circle(at(50, 58), 13 * scale, color="white"))
    pupil_y = 63 if feeling == "worried" else 60
    ax.add_patch(Circle(at(51, pupil_y), 6 * scale, color="#111111"))
    if feeling == "worried":
        (x0, y0), (x1, y1) = at(36, 42), at(62, 48)
        ax.plot([x0, x1], [y0, y1], color="#111111", linewidth=size / 30, solid_capstyle="round")


def canvas(width: int, height: int):
    fig = plt.figure(figsize=(width / 100, height / 100), dpi=100)
    ax = fig.add_axes((0, 0, 1, 1))
    ax.set_xlim(0, width)
    ax.set_ylim(0, height)
    ax.axis("off")
    fig.patch.set_facecolor(GROUND)
    return fig, ax


def text(ax, x, y, s, size, colour=TEXT, weight="bold") -> None:
    ax.text(
        x, y, s, ha="center", va="center", fontsize=size, color=colour, weight=weight, wrap=True
    )


def story(feed: dict, path: Path) -> None:
    fig, ax = canvas(1080, 1920)
    text(ax, 540, 1800, "AgniNetra", 44, EMBER)
    text(ax, 540, 1710, "The Evening Match", 38)
    text(ax, 540, 1650, feed["evening_ist"], 24, MUTED, "normal")
    draw_netu(ax, 540, 1330, 360, mood(feed))
    match = feed["match"]
    text(ax, 540, 980, f"Polar {pct(match['polar_share'])}", 44, POLAR)
    text(ax, 540, 880, f"INSAT {pct(match['insat_share'])}", 44, EMBER)
    text(ax, 540, 810, "share of today's fire cells each caught", 22, MUTED, "normal")
    if match["polar_last_seen_ist"]:
        text(ax, 540, 700, f"Polar all out at {match['polar_last_seen_ist']}", 28)
    text(ax, 540, 330, "how sure: low. Weak labels. Not an official count.", 20, SURE)
    text(ax, 540, 250, "Data Source MOSDAC/SAC/ISRO. NASA FIRMS.", 16, MUTED, "normal")
    text(ax, 540, 210, "Boundaries (c) OpenStreetMap contributors, ODbL.", 16, MUTED, "normal")
    fig.savefig(path, facecolor=GROUND)
    plt.close(fig)


def square(feed: dict, path: Path) -> None:
    fig, ax = canvas(1080, 1080)
    text(ax, 540, 990, "Did the satellites see it?", 36)
    draw_netu(ax, 270, 560, 300, mood(feed))
    match = feed["match"]
    text(ax, 760, 640, f"Polar {pct(match['polar_share'])}", 30, POLAR)
    text(ax, 760, 560, f"INSAT {pct(match['insat_share'])}", 30, EMBER)
    text(ax, 760, 490, feed["evening_ist"], 20, MUTED, "normal")
    text(ax, 540, 150, "how sure: low. Not an official count.", 18, SURE)
    text(ax, 540, 90, "MOSDAC/SAC/ISRO, NASA FIRMS, OSM (ODbL)", 14, MUTED, "normal")
    fig.savefig(path, facecolor=GROUND)
    plt.close(fig)


def sticker(feeling: str, label: str, path: Path) -> None:
    """A 512 by 512 WebP with a transparent ground, the size WhatsApp stickers need."""
    fig, ax = canvas(512, 512)
    fig.patch.set_alpha(0)
    draw_netu(ax, 256, 300, 280, feeling)
    text(ax, 256, 50, label, 30)
    png = path.with_suffix(".png")
    fig.savefig(png, transparent=True)
    plt.close(fig)
    Image.open(png).convert("RGBA").resize((512, 512)).save(path, "WEBP", quality=80)
    png.unlink()


def caption(feed: dict) -> str:
    match = feed["match"]
    if match["insat_share"] is None and match["polar_share"] is None:
        first = CAPTIONS["quiet"].format(day=feed["evening_ist"])
    else:
        first = CAPTIONS["match"].format(
            day=feed["evening_ist"],
            polar=pct(match["polar_share"]),
            insat=pct(match["insat_share"]),
            polar_last=match["polar_last_seen_ist"] or "the afternoon",
        )
    tomorrow = feed["tomorrow"]
    parts = [first]
    if tomorrow["pm25_24h_mean"] is not None:
        parts.append(
            CAPTIONS["tomorrow"].format(
                city=tomorrow["city"],
                pm25=round(tomorrow["pm25_24h_mean"]),
                category=tomorrow["cpcb_category"],
            )
        )
    parts.append(CAPTIONS["credits"])
    return "\n\n".join(parts) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--feed", type=Path, default=FEED)
    args = parser.parse_args()
    feed = json.loads(args.feed.read_text())
    folder = OUT / feed["evening_ist"]
    (folder / "stickers").mkdir(parents=True, exist_ok=True)
    story(feed, folder / "story.png")
    square(feed, folder / "square.png")
    (folder / "caption.txt").write_text(caption(feed))
    for feeling, label in (
        ("watchful", "Netu is watching"),
        ("worried", "Bad air, stay in"),
        ("resting", "Quiet sky"),
    ):
        sticker(feeling, label, folder / "stickers" / f"netu_{feeling}.webp")
    print(f"social kit written to {folder.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
