"""Copernicus Data Space catalogue queries.

The OData catalogue answers anonymously, so coverage and cloud cover are
established before an account exists. Only the download needs a token. D36.
"""

import json
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime
from typing import Final

ODATA_ROOT: Final[str] = "https://catalogue.dataspace.copernicus.eu/odata/v1/Products"
REQUEST_TIMEOUT_S: Final[float] = 60.0


class CatalogueError(RuntimeError):
    """Raised when the catalogue is unreachable or answers with an unusable body."""


@dataclass(frozen=True)
class Product:
    product_id: str
    name: str
    sensing_start: datetime
    size_bytes: int
    online: bool
    cloud_cover_pct: float | None
    footprint_wkt: str | None

    @property
    def size_gb(self) -> float:
        return self.size_bytes / 1e9


def _parse_footprint(raw: str | None) -> str | None:
    """Strip the OData geography prefix, leaving plain WKT.

    The API returns geography'SRID=4326;POLYGON ((...))'. DuckDB's ST_GeomFromText
    rejects that wrapper, and a caller that forgets to strip it gets a parse error
    rather than a wrong answer, which is why this is done once here.
    """
    if raw is None:
        return None
    marker = ";"
    if marker in raw:
        raw = raw.split(marker, 1)[1]
    return raw.rstrip("'").strip()


def _to_product(entry: dict) -> Product:
    attributes = {a["Name"]: a.get("Value") for a in entry.get("Attributes", [])}
    cloud = attributes.get("cloudCover")
    return Product(
        product_id=entry["Id"],
        name=entry["Name"],
        sensing_start=datetime.fromisoformat(entry["ContentDate"]["Start"].replace("Z", "+00:00")),
        size_bytes=int(entry["ContentLength"]),
        online=bool(entry.get("Online", False)),
        cloud_cover_pct=float(cloud) if cloud is not None else None,
        footprint_wkt=_parse_footprint(entry.get("Footprint")),
    )


def search_l2a(
    *,
    longitude: float,
    latitude: float,
    start: datetime,
    end: datetime,
    limit: int = 50,
) -> list[Product]:
    """Return Sentinel-2 L2A products intersecting the point, sorted by cloud cover.

    Raises CatalogueError on transport failure or an unparseable body. Never
    returns an empty list silently as success: an empty result is returned as an
    empty list and the caller decides, because zero products over a known covered
    belt indicates a bad query rather than absent data.
    """
    query = (
        "Collection/Name eq 'SENTINEL-2' and "
        f"OData.CSC.Intersects(area=geography'SRID=4326;POINT({longitude} {latitude})') and "
        f"ContentDate/Start gt {start.strftime('%Y-%m-%dT%H:%M:%S.000Z')} and "
        f"ContentDate/Start lt {end.strftime('%Y-%m-%dT%H:%M:%S.000Z')} and "
        "contains(Name,'MSIL2A')"
    )
    url = f"{ODATA_ROOT}?" + urllib.parse.urlencode(
        {"$filter": query, "$expand": "Attributes", "$top": str(limit)}
    )
    try:
        with urllib.request.urlopen(url, timeout=REQUEST_TIMEOUT_S) as response:
            body = json.loads(response.read().decode("utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise CatalogueError(f"catalogue query failed: {exc}") from exc

    products = [_to_product(e) for e in body.get("value", [])]
    products.sort(key=lambda p: (p.cloud_cover_pct is None, p.cloud_cover_pct or 0.0))
    return products
