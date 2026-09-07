"""Authenticated access to MOSDAC, the ISRO data portal.

Credentials are read from the environment and never logged, printed or written to
disk. That is the same contract the FIRMS map key and the Copernicus credentials
are held under, and it is why this module exists rather than the `config.json` the
vendor client uses: that file wants a username and password sitting on disk next to
the code.

The endpoints and request shapes are taken from the vendor client `mdapi.py`,
downloaded from mosdac.gov.in and read before anything was run. It contains no
`eval`, `exec`, `subprocess`, `pickle` or archive extraction, and every endpoint it
contacts is on mosdac.gov.in.
"""

import json
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Final

TOKEN_URL: Final[str] = "https://mosdac.gov.in/download_api/gettoken"
DOWNLOAD_URL: Final[str] = "https://mosdac.gov.in/download_api/download"
SEARCH_URL: Final[str] = "https://mosdac.gov.in/apios/datasets.json"

# INSAT-3DS Imager, Level 1B standard, six channels at a half hour cadence.
INSAT_3DS_L1B: Final[str] = "3SIMG_L1B_STD"

CHUNK_BYTES: Final[int] = 8 * 1024 * 1024
REQUEST_TIMEOUT_S: Final[float] = 120.0


class MissingCredentialsError(RuntimeError):
    """Raised when a required environment variable is absent or empty."""


class MosdacError(RuntimeError):
    """Raised when MOSDAC rejects a request or returns an unusable body."""


@dataclass(frozen=True)
class Granule:
    granule_id: str
    identifier: str
    acquired: str
    size_mb: float | None

    @property
    def is_hdf5(self) -> bool:
        return self.identifier.endswith(".h5")


def search(dataset_id: str, start: str, end: str) -> list[Granule]:
    """List granules for a dataset over a date range. Anonymous, no token needed.

    Dates are `YYYY-MM-DD`. Raises MosdacError on a transport failure or an
    unparseable body, never an empty list dressed as success: an empty result is
    returned as an empty list and the caller decides what that means.
    """
    url = f"{SEARCH_URL}?" + urllib.parse.urlencode(
        {"datasetId": dataset_id, "startTime": start, "endTime": end}
    )
    try:
        with urllib.request.urlopen(url, timeout=REQUEST_TIMEOUT_S) as response:
            body = json.loads(response.read().decode("utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise MosdacError(f"granule search failed: {exc}") from exc

    if body.get("statusCode") == 500:
        raise MosdacError(f"MOSDAC rejected the search: {body.get('message')}")

    granules = []
    for entry in body.get("entries") or []:
        granules.append(
            Granule(
                granule_id=str(entry.get("id")),
                identifier=str(entry.get("identifier")),
                acquired=str(entry.get("dcDate", "")).split("/")[0],
                size_mb=None,
            )
        )
    return sorted(granules, key=lambda g: g.identifier)


def access_token(username: str | None, password: str | None) -> str:
    """Exchange credentials for a bearer token.

    Raises MissingCredentialsError before any request is made if either value is
    absent, so a misconfigured environment fails without a network round trip that
    might log a partial attempt. The submitted values never appear in an error.
    """
    if not username:
        raise MissingCredentialsError("MOSDAC_USERNAME is not set in the environment")
    if not password:
        raise MissingCredentialsError("MOSDAC_PASSWORD is not set in the environment")

    payload = json.dumps({"username": username, "password": password}).encode("utf-8")
    request = urllib.request.Request(TOKEN_URL, data=payload, method="POST")
    request.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT_S) as response:
            body = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raise MosdacError(
            f"MOSDAC returned {exc.code} for the token request. The credentials were "
            "rejected or the account is not approved. The submitted values are not shown."
        ) from exc
    except OSError as exc:
        raise MosdacError(f"MOSDAC unreachable: {exc}") from exc

    token = body.get("access_token") or body.get("token")
    if not token:
        raise MosdacError(f"MOSDAC returned no token. Keys present: {sorted(body)}")
    return str(token)


def download(granule_id: str, token: str, destination: Path, attempts: int = 6) -> int:
    """Stream one granule to disk, resuming a partial transfer, and return its size.

    The link drops. A first attempt at a 438 MB granule stopped at 188 MB, and the
    vendor client ships a retry ladder, so interruption is the expected case rather
    than the exception. Each attempt sends a Range header for the bytes already on
    disk, so a retry costs the remainder rather than the whole file.

    The completed size is checked against the declared length and the file is only
    renamed into place if they agree. A truncated HDF5 can still open and return
    plausible arrays, so a silent short read is worse than a failure.
    """
    partial = destination.with_suffix(destination.suffix + ".part")
    partial.parent.mkdir(parents=True, exist_ok=True)
    url = f"{DOWNLOAD_URL}?" + urllib.parse.urlencode({"id": granule_id})

    expected: int | None = None
    for attempt in range(1, attempts + 1):
        have = partial.stat().st_size if partial.exists() else 0
        if expected is not None and have >= expected:
            break

        request = urllib.request.Request(url)
        request.add_header("Authorization", f"Bearer {token}")
        if have:
            request.add_header("Range", f"bytes={have}-")

        try:
            with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT_S) as response:
                if response.status == 206:
                    content_range = response.headers.get("Content-Range", "")
                    if "/" in content_range:
                        expected = int(content_range.rsplit("/", 1)[1])
                    mode = "ab"
                else:
                    declared = response.headers.get("Content-Length")
                    expected = int(declared) if declared else expected
                    # The server ignored the Range header and restarted the body.
                    have, mode = 0, "wb"

                with partial.open(mode) as handle:
                    while True:
                        chunk = response.read(CHUNK_BYTES)
                        if not chunk:
                            break
                        handle.write(chunk)
                        have += len(chunk)
        except (OSError, urllib.error.HTTPError) as exc:
            if attempt == attempts:
                raise MosdacError(
                    f"transfer of {granule_id} failed after {attempt} attempts with "
                    f"{have} of {expected} bytes: {exc}"
                ) from exc
            time.sleep(min(120, 10 * attempt))
            continue

        if expected is None or have >= expected:
            break
        if attempt == attempts:
            raise MosdacError(
                f"transfer of {granule_id} stalled at {have} of {expected} bytes "
                f"after {attempts} attempts"
            )
        time.sleep(min(120, 10 * attempt))

    written = partial.stat().st_size
    if expected is not None and written != expected:
        raise MosdacError(
            f"transfer of {granule_id} wrote {written} bytes against a declared "
            f"{expected}. The partial file is kept at {partial.name} so a rerun resumes."
        )
    partial.replace(destination)
    return written
