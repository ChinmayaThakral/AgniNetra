"""Global Energy Monitor tracker loading, with status filtering and operating windows.

Two rules govern what becomes a usable industrial reference asset.

Status. A tracker row is a location on paper until the facility is built. Cancelled,
announced, proposed, pre-construction, shelved and in-construction units have
coordinates but emit nothing, and admitting them would manufacture weak labels for
facilities that do not exist while diluting the industrial lift for a reason
invisible in the output. Only statuses meaning the facility was built and has
operated at some point are kept. D28.

Operating window. Units start and some retire, and the detections span 2023, 2024
and 2026. A unit retired in 2024 is a valid reference for a 2023 detection and not
for a 2026 one. The window is carried on every asset and enforced at the join. D29.
"""

from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Final

import openpyxl

# Statuses meaning the facility was built and has emitted heat at some point. The
# operating window then decides whether it emitted at a given detection's date.
KEPT_STATUSES: Final[frozenset[str]] = frozenset(
    {"operating", "retired", "mothballed", "operating pre-retirement"}
)

# Statuses meaning the facility does not exist on the ground. Listed explicitly
# rather than inferred by exclusion, so an unfamiliar status value fails loudly.
DROPPED_STATUSES: Final[frozenset[str]] = frozenset(
    {
        "cancelled",
        "announced",
        "proposed",
        "pre-construction",
        "construction",
        "shelved",
        "permitted",
        "unknown",
    }
)


class UnknownStatusError(ValueError):
    """Raised when a tracker carries a status not in either list."""


class AssetWindowError(RuntimeError):
    """Raised when an asset is matched to a detection outside its operating window."""


@dataclass(frozen=True)
class Asset:
    """One industrial asset with a coordinate and an operating window."""

    sector: str
    tracker: str
    name: str
    latitude: float
    longitude: float
    status: str
    start_year: int | None
    retired_year: int | None
    capacity: float | None
    subnational: str | None

    def operating_in(self, when: date) -> bool:
        """Whether the asset was operating in the year of a detection.

        An unknown start year is treated as operating from before the record, which
        is the permissive reading. An unknown retired year on a kept status is
        treated as still operating. Both choices are recorded in D29 and their
        effect is measured rather than assumed.
        """
        year = when.year
        if self.start_year is not None and year < self.start_year:
            return False
        return not (self.retired_year is not None and year > self.retired_year)


def normalise_status(raw: object) -> str:
    """Lower case and strip a status, collapsing GEM's inferred suffixes.

    GEM writes values like 'shelved - inferred 2 y' and 'cancelled - inferred 4 y'.
    The inference qualifier does not change what the status means for us.
    """
    text = str(raw or "").strip().lower()
    if " - inferred" in text:
        text = text.split(" - inferred")[0].strip()
    return text


def status_is_kept(raw: object) -> bool:
    """Whether a status means the facility exists. Raises on an unknown value."""
    status = normalise_status(raw)
    if status in KEPT_STATUSES:
        return True
    if status in DROPPED_STATUSES or status in ("", "none"):
        return False
    raise UnknownStatusError(
        f"status {status!r} is in neither the kept nor the dropped list. "
        "Classify it explicitly rather than letting it fall through."
    )


def parse_year(raw: object) -> int | None:
    """Parse GEM's several date shapes into a year.

    The trackers mix datetime values, bare float years, 'unknown', and empty cells
    in the same column.
    """
    if raw is None:
        return None
    if hasattr(raw, "year"):
        return int(raw.year)
    text = str(raw).strip()
    if not text or text.lower() in ("unknown", "n/a", "none", "tbd"):
        return None
    try:
        value = int(float(text))
    except ValueError:
        return None
    return value if 1800 <= value <= 2100 else None


def parse_coordinates(row: tuple, index: dict[str, int]) -> tuple[float, float] | None:
    """Read a coordinate from either separate columns or a combined field."""
    if "latitude" in index and "longitude" in index:
        lat, lon = row[index["latitude"]], row[index["longitude"]]
        if lat is None or lon is None:
            return None
        try:
            return float(lat), float(lon)
        except (TypeError, ValueError):
            return None
    if "coordinates" in index:
        raw = row[index["coordinates"]]
        if raw is None:
            return None
        parts = str(raw).replace(";", ",").split(",")
        if len(parts) != 2:
            return None
        try:
            return float(parts[0].strip()), float(parts[1].strip())
        except ValueError:
            return None
    return None


def load_tracker(
    path: Path,
    sheet: str,
    sector: str,
    country_column: str,
    status_column: str | None,
    name_column: str,
    start_column: str | None = None,
    retired_column: str | None = None,
    capacity_column: str | None = None,
    subnational_column: str | None = None,
    status_by_id: dict[str, str] | None = None,
    id_column: str | None = None,
    country: str = "India",
) -> tuple[list[Asset], dict[str, int]]:
    """Load one tracker sheet, returning kept assets and a status tally."""
    workbook = openpyxl.load_workbook(path, read_only=True, data_only=True)
    sheet_obj = workbook[sheet]
    rows = sheet_obj.iter_rows(values_only=True)
    header = [str(cell).strip() if cell is not None else "" for cell in next(rows)]
    index = {name.lower(): position for position, name in enumerate(header)}

    def column(name: str | None) -> int | None:
        return index.get(name.lower()) if name else None

    country_index = column(country_column)
    status_index = column(status_column)
    name_index = column(name_column)
    start_index = column(start_column)
    retired_index = column(retired_column)
    capacity_index = column(capacity_column)
    subnational_index = column(subnational_column)
    id_index = column(id_column)

    assets: list[Asset] = []
    tally: dict[str, int] = {}

    for row in rows:
        if country_index is None or str(row[country_index]).strip() != country:
            continue
        if status_by_id is not None and id_index is not None:
            raw_status = status_by_id.get(str(row[id_index]).strip(), "")
        else:
            raw_status = row[status_index] if status_index is not None else ""
        status = normalise_status(raw_status)
        tally[status or "blank"] = tally.get(status or "blank", 0) + 1
        if not status_is_kept(raw_status):
            continue
        coordinate = parse_coordinates(row, index)
        if coordinate is None:
            continue
        latitude, longitude = coordinate
        capacity_raw = row[capacity_index] if capacity_index is not None else None
        try:
            capacity = float(capacity_raw) if capacity_raw is not None else None
        except (TypeError, ValueError):
            capacity = None
        assets.append(
            Asset(
                sector=sector,
                tracker=path.name,
                name=str(row[name_index] or "").strip() if name_index is not None else "",
                latitude=latitude,
                longitude=longitude,
                status=status,
                start_year=parse_year(row[start_index]) if start_index is not None else None,
                retired_year=(
                    parse_year(row[retired_index]) if retired_index is not None else None
                ),
                capacity=capacity,
                subnational=(
                    str(row[subnational_index] or "").strip()
                    if subnational_index is not None
                    else None
                ),
            )
        )
    workbook.close()
    return assets, tally


def assert_asset_valid_for(
    start_year: int | None,
    retired_year: int | None,
    detection_date: date,
    asset_label: str = "asset",
) -> None:
    """Refuse an asset matched to a detection outside its operating window.

    This is the same shape as the recurrence leakage guard and exists for the same
    reason. A join that silently drops out of window assets and one that never
    checks produce the same shaped output, and only the guard distinguishes them.
    Raising means a naive join fails loudly instead of quietly labelling a 2026
    detection against a plant that retired in 2024.
    """
    year = detection_date.year
    if start_year is not None and year < start_year:
        raise AssetWindowError(
            f"{asset_label} starts in {start_year} but was matched to a detection on "
            f"{detection_date.isoformat()}. The plant did not exist yet."
        )
    if retired_year is not None and year > retired_year:
        raise AssetWindowError(
            f"{asset_label} retired in {retired_year} but was matched to a detection on "
            f"{detection_date.isoformat()}. The plant was already shut."
        )
