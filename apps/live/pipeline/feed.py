"""The Live feed: classification, aggregation, the match and Netu's lines.

Pure functions only. Nothing here touches the network or the clock, so every rule the
app promises is testable on fixed inputs. `build_feed.py` fetches and calls these.

The rules the app does not bend are enforced here rather than in the interface:
detections leave this module only as 0.1 degree cells, never as points; the match is
scored as shares, never counts; every sentence Netu says is a template filled from the
feed; and no confidence is ever stated as high, because every class is a weak label.
"""

import math
from collections import Counter, defaultdict
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

SCHEMA = "agninetra-live/1"
IST = timezone(timedelta(hours=5, minutes=30))
CELL_DEG = 0.1
EARTH_RADIUS_M = 6371008.8
INDUSTRIAL_RADIUS_M = 1000.0
FLARE_RADIUS_M = 500.0
# The window a fire must fall in to count for the day's match, and the evening overs.
MATCH_START_IST = 10
MATCH_END_IST = 20
OVER_SLOTS_IST = tuple((16 + i // 2, 30 * (i % 2)) for i in range(8))
CROPLAND_AGRICULTURAL = 0.5
CROPLAND_MEDIUM = 0.8
CROPLAND_MEDIUM_MIN_SAMPLES = 20

CAVEATS = (
    "Classes are weak labels from maps, not checked on the ground.",
    "Not an official count.",
    "Fires are shown per 11 km cell, never as individual fields.",
)


@dataclass(frozen=True)
class Fire:
    """One detection as the feed sees it. Never serialised as a point."""

    longitude: float
    latitude: float
    when_utc: datetime
    team: str  # "polar" or "insat"


def cell_of(*, longitude: float, latitude: float) -> tuple[int, int]:
    return (math.floor(longitude / CELL_DEG), math.floor(latitude / CELL_DEG))


def cell_centre(cell: tuple[int, int]) -> tuple[float, float]:
    return (round((cell[0] + 0.5) * CELL_DEG, 3), round((cell[1] + 0.5) * CELL_DEG, 3))


def _haversine_m(*, lon1: float, lat1: float, lon2: float, lat2: float) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * EARTH_RADIUS_M * math.asin(math.sqrt(a))


class PointIndex:
    """Reference points bucketed by cell, for radius lookups without a spatial library."""

    def __init__(self, points: Iterable[tuple[float, float]]) -> None:
        self._buckets: dict[tuple[int, int], list[tuple[float, float]]] = defaultdict(list)
        for lon, lat in points:
            self._buckets[cell_of(longitude=lon, latitude=lat)].append((lon, lat))

    def within(self, *, longitude: float, latitude: float, radius_m: float) -> bool:
        cx, cy = cell_of(longitude=longitude, latitude=latitude)
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                for lon, lat in self._buckets.get((cx + dx, cy + dy), ()):
                    distance = _haversine_m(lon1=longitude, lat1=latitude, lon2=lon, lat2=lat)
                    if distance <= radius_m:
                        return True
        return False


class Reference:
    """The committed reference pack, indexed. See build_reference_pack.py."""

    def __init__(self, pack: dict, year: int) -> None:
        operating = [
            (lon, lat)
            for lon, lat, _sector, start, retired in pack["gem"]
            if (start is None or start <= year) and (retired is None or retired >= year)
        ]
        self.industrial = PointIndex([tuple(p) for p in pack["osm"]["industrial"]] + operating)
        self.flare = PointIndex(tuple(p) for p in pack["osm"]["flare"])
        self.cropland = {(cx, cy): (n, share) for cx, cy, n, share in pack["cropland"]}
        self.attribution = list(pack["attribution"])


def classify_cell(
    fires: list[Fire], reference: Reference, cell: tuple[int, int]
) -> tuple[str, str]:
    """A cell's likely class and how sure, from the fires in it.

    Flare and industrial need a registry point within the label radius of a majority of
    the cell's fires. Only a polar fire, at 375 m, is fine enough to trust a 500 m or
    1 km radius; a cell backed by 4 km INSAT pixels alone is low confidence. Agricultural
    reads the cell's cropland share. Nothing is ever high: these are weak labels.
    """
    votes: Counter = Counter()
    polar_votes: Counter = Counter()
    for fire in fires:
        if reference.flare.within(
            longitude=fire.longitude, latitude=fire.latitude, radius_m=FLARE_RADIUS_M
        ):
            label = "flare"
        elif reference.industrial.within(
            longitude=fire.longitude, latitude=fire.latitude, radius_m=INDUSTRIAL_RADIUS_M
        ):
            label = "industrial"
        else:
            label = "other"
        votes[label] += 1
        if fire.team == "polar":
            polar_votes[label] += 1
    for label in ("flare", "industrial"):
        if votes[label] * 2 > len(fires):
            return label, "medium" if polar_votes[label] else "low"
    samples, share = reference.cropland.get(cell, (0, None))
    if share is not None and share >= CROPLAND_AGRICULTURAL:
        sure = share >= CROPLAND_MEDIUM and samples >= CROPLAND_MEDIUM_MIN_SAMPLES
        return "agricultural", "medium" if sure else "low"
    return "unclassified", "low"


def in_match_window(when_utc: datetime) -> bool:
    return MATCH_START_IST <= when_utc.astimezone(IST).hour < MATCH_END_IST


def slot_of(when_utc: datetime) -> tuple[int, int]:
    local = when_utc.astimezone(IST)
    return (local.hour, 30 * (local.minute // 30))


def share(part: int, whole: int) -> float | None:
    return None if whole == 0 else round(part / whole, 3)


def build_match(fires: list[Fire]) -> dict:
    """The Evening Match, scored as shares of fire cells, never as counts.

    The universe is every cell any satellite saw burning between 10:00 and 20:00 IST.
    Each team's score is the share of that universe it caught. Overs are the half hours
    from 16:00 to 19:30, each reporting the cumulative shares after that over. A team is
    all out once its last detection of the day has passed.
    """
    in_window = [f for f in fires if in_match_window(f.when_utc)]
    universe = {cell_of(longitude=f.longitude, latitude=f.latitude) for f in in_window}
    caught: dict[str, set] = {"polar": set(), "insat": set()}
    last_seen: dict[str, datetime | None] = {"polar": None, "insat": None}
    by_slot: dict[tuple[int, int], dict[str, set]] = defaultdict(lambda: defaultdict(set))
    for f in in_window:
        cell = cell_of(longitude=f.longitude, latitude=f.latitude)
        by_slot[slot_of(f.when_utc)][f.team].add(cell)
        if last_seen[f.team] is None or f.when_utc > last_seen[f.team]:
            last_seen[f.team] = f.when_utc

    before_overs = {"polar": set(), "insat": set()}
    for slot, teams in by_slot.items():
        if slot < OVER_SLOTS_IST[0]:
            for team, cells in teams.items():
                before_overs[team] |= cells
    running = {team: set(cells) for team, cells in before_overs.items()}
    overs = []
    for slot in OVER_SLOTS_IST:
        for team in running:
            running[team] |= by_slot.get(slot, {}).get(team, set())
        overs.append(
            {
                "over": f"{slot[0]:02d}:{slot[1]:02d}",
                "polar_share": share(len(running["polar"]), len(universe)),
                "insat_share": share(len(running["insat"]), len(universe)),
                "polar_new": bool(by_slot.get(slot, {}).get("polar")),
                "insat_new": bool(by_slot.get(slot, {}).get("insat")),
            }
        )
    for team in caught:
        caught[team] = {
            cell_of(longitude=f.longitude, latitude=f.latitude) for f in in_window if f.team == team
        }
    return {
        "window_ist": f"{MATCH_START_IST:02d}:00 to {MATCH_END_IST:02d}:00",
        "polar_share": share(len(caught["polar"]), len(universe)),
        "insat_share": share(len(caught["insat"]), len(universe)),
        "polar_last_seen_ist": _ist(last_seen["polar"]),
        "insat_last_seen_ist": _ist(last_seen["insat"]),
        "overs": overs,
    }


def _ist(when: datetime | None) -> str | None:
    return None if when is None else when.astimezone(IST).strftime("%H:%M")


def restrict_to_india(fires: list[Fire], locate) -> tuple[list[Fire], dict]:
    """Keep fires whose cell centre lies in an Indian state, and the lookup for each cell.

    The download box is a rectangle, and 41 percent of what it returns lies outside India,
    D23, so without this the match would score Pakistani and Bangladeshi fires. Deciding by
    the cell centre rather than the point keeps a border cell whole on one side.
    """
    places: dict[tuple[int, int], tuple[str | None, str | None]] = {}
    kept = []
    for f in fires:
        cell = cell_of(longitude=f.longitude, latitude=f.latitude)
        if cell not in places:
            lon, lat = cell_centre(cell)
            places[cell] = locate(longitude=lon, latitude=lat)
        if places[cell][0] is not None:
            kept.append(f)
    return kept, places


def build_cells(fires: list[Fire], reference: Reference, district_of) -> list[dict]:
    """Cells, never points. `district_of` maps a cell centre to (state, district)."""
    grouped: dict[tuple[int, int], list[Fire]] = defaultdict(list)
    for f in fires:
        grouped[cell_of(longitude=f.longitude, latitude=f.latitude)].append(f)
    cells = []
    for cell in sorted(grouped):
        members = grouped[cell]
        label, sure = classify_cell(members, reference, cell)
        lon, lat = cell_centre(cell)
        state, district = district_of(longitude=lon, latitude=lat)
        evening = [f for f in members if f.when_utc.astimezone(IST).hour >= 16]
        cells.append(
            {
                "cell": f"{cell[0]}_{cell[1]}",
                "centre": [lon, lat],
                "state": state,
                "district": district,
                "class": label,
                "how_sure": sure,
                "seen_by": sorted({f.team for f in members}),
                "evening": bool(evening),
            }
        )
    return cells


def build_districts(cells: list[dict]) -> list[dict]:
    """Per district: how many burning cells each satellite saw, and the evening share."""
    grouped: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for c in cells:
        if c["district"]:
            grouped[(c["state"], c["district"])].append(c)
    out = []
    # A cell can sit in a district and outside every state polygon, where the OSM
    # boundaries leave a gap, so a missing state sorts as empty rather than raising.
    for (state, district), members in sorted(
        grouped.items(), key=lambda kv: (kv[0][0] or "", kv[0][1])
    ):
        out.append(
            {
                "state": state,
                "district": district,
                "cells": len(members),
                "polar_share": share(sum("polar" in c["seen_by"] for c in members), len(members)),
                "insat_share": share(sum("insat" in c["seen_by"] for c in members), len(members)),
                "evening_share": share(sum(c["evening"] for c in members), len(members)),
            }
        )
    return out


# Every sentence Netu says. Placeholders are filled from the feed and nothing else.
TEMPLATES = {
    "polar_all_out": "Polar satellites all out at {polar_last}. INSAT still batting.",
    "both_quiet": "Polar satellites out at {polar_last}, and INSAT's last catch was {insat_last}.",
    "insat_share": "INSAT has caught {insat_pct} percent of today's fire cells so far.",
    "polar_share": "The 1:30 pm pass caught {polar_pct} percent. The evening was not its shift.",
    "quiet": "Quiet sky today. Netu is resting its eye.",
    "worried": "Heavy smoke evening. Netu is worried, not excited.",
    "data_late": "INSAT data here is from {insat_age}. Live layer: NASA FIRMS.",
}


def netu_lines(match: dict, insat_delay_hours: float | None, heavy: bool) -> list[dict]:
    lines = []

    def say(key: str, **values: object) -> None:
        lines.append({"template": key, "text": TEMPLATES[key].format(**values)})

    if match["insat_share"] is None and match["polar_share"] is None:
        say("quiet")
        return lines
    if heavy:
        say("worried")
    polar_last, insat_last = match["polar_last_seen_ist"], match["insat_last_seen_ist"]
    if polar_last:
        # "Still batting" is only true when INSAT caught something after the polar pass.
        if insat_last and insat_last > polar_last:
            say("polar_all_out", polar_last=polar_last)
        else:
            say("both_quiet", polar_last=polar_last, insat_last=insat_last or "none")
    if match["insat_share"] is not None:
        say("insat_share", insat_pct=round(100 * match["insat_share"]))
    if match["polar_share"] is not None:
        say("polar_share", polar_pct=round(100 * match["polar_share"]))
    if insat_delay_hours is not None and insat_delay_hours >= 24:
        say("data_late", insat_age=f"{round(insat_delay_hours / 24)} days ago")
    return lines


# CPCB National AQI breakpoints for 24 hour PM2.5, micrograms per cubic metre.
PM25_CATEGORIES = (
    (30, "Good"),
    (60, "Satisfactory"),
    (90, "Moderate"),
    (120, "Poor"),
    (250, "Very Poor"),
    (math.inf, "Severe"),
)


def pm25_category(value: float | None) -> str | None:
    if value is None:
        return None
    for upper, name in PM25_CATEGORIES:
        if value <= upper:
            return name
    return None


def validate(feed: dict) -> None:
    """Raise if the feed breaks a rule the app promises. Run before every write."""
    if feed.get("schema") != SCHEMA:
        raise ValueError("wrong schema")
    for c in feed["cells"]:
        if set(c) != {
            "cell",
            "centre",
            "state",
            "district",
            "class",
            "how_sure",
            "seen_by",
            "evening",
        }:
            raise ValueError(f"cell carries unexpected fields: {sorted(c)}")
        if c["how_sure"] not in ("low", "medium"):
            raise ValueError(f"confidence {c['how_sure']} is not allowed for a weak label")
    for key in ("polar_share", "insat_share"):
        value = feed["match"][key]
        if value is not None and not 0 <= value <= 1:
            raise ValueError(f"{key} is not a share: {value}")
    for line in feed["netu"]:
        if line["template"] not in TEMPLATES:
            raise ValueError(f"Netu said something outside the templates: {line}")
    if not feed.get("attribution") or not feed.get("caveats"):
        raise ValueError("attribution and caveats must travel with the data")
