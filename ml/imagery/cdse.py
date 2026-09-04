"""Authenticated access to Copernicus Data Space.

Credentials are read from the environment and never logged, printed or written
to disk, which is the same contract the FIRMS map key is held under. A failure
names the missing variable, never its value.
"""

import json
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Final

TOKEN_URL: Final[str] = (
    "https://identity.dataspace.copernicus.eu/auth/realms/CDSE/protocol/openid-connect/token"
)
DOWNLOAD_ROOT: Final[str] = "https://catalogue.dataspace.copernicus.eu/odata/v1/Products"
PUBLIC_CLIENT_ID: Final[str] = "cdse-public"
CHUNK_BYTES: Final[int] = 8 * 1024 * 1024


class MissingCredentialsError(RuntimeError):
    """Raised when a required environment variable is absent or empty."""


class AuthError(RuntimeError):
    """Raised when the identity service rejects the credentials."""


class DownloadError(RuntimeError):
    """Raised when a product transfer fails or completes at the wrong size."""


def access_token(username: str | None, password: str | None) -> str:
    """Exchange credentials for a bearer token.

    The password is passed straight through to the identity service and is never
    held anywhere else. Raises MissingCredentialsError before any request is made
    if either value is absent, so a misconfigured environment fails without a
    network round trip that might log a partial attempt.
    """
    if not username:
        raise MissingCredentialsError("CDSE_USERNAME is not set in the environment")
    if not password:
        raise MissingCredentialsError("CDSE_PASSWORD is not set in the environment")

    payload = urllib.parse.urlencode(
        {
            "grant_type": "password",
            "username": username,
            "password": password,
            "client_id": PUBLIC_CLIENT_ID,
        }
    ).encode("utf-8")

    request = urllib.request.Request(TOKEN_URL, data=payload, method="POST")
    request.add_header("Content-Type", "application/x-www-form-urlencoded")
    try:
        with urllib.request.urlopen(request, timeout=60.0) as response:
            body = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raise AuthError(
            f"identity service returned {exc.code}. The credentials were rejected or the "
            "account is not activated. The submitted values are not shown."
        ) from exc
    except OSError as exc:
        raise AuthError(f"identity service unreachable: {exc}") from exc

    token = body.get("access_token")
    if not token:
        raise AuthError("identity service returned no access_token")
    return token


def download_product(product_id: str, token: str, destination: Path) -> int:
    """Stream one product to disk and return the byte count written.

    Downloads to a .part file and renames on completion, so an interrupted
    transfer cannot be mistaken for a complete product by a later run.
    """
    partial = destination.with_suffix(destination.suffix + ".part")
    partial.parent.mkdir(parents=True, exist_ok=True)

    request = urllib.request.Request(f"{DOWNLOAD_ROOT}({product_id})/$value")
    request.add_header("Authorization", f"Bearer {token}")

    written = 0
    try:
        with urllib.request.urlopen(request, timeout=300.0) as response:
            declared = response.headers.get("Content-Length")
            expected = int(declared) if declared else None
            with partial.open("wb") as handle:
                while True:
                    chunk = response.read(CHUNK_BYTES)
                    if not chunk:
                        break
                    handle.write(chunk)
                    written += len(chunk)
    except (OSError, urllib.error.HTTPError) as exc:
        partial.unlink(missing_ok=True)
        raise DownloadError(
            f"transfer of {product_id} failed after {written} bytes: {exc}"
        ) from exc

    if expected is not None and written != expected:
        partial.unlink(missing_ok=True)
        raise DownloadError(
            f"transfer of {product_id} wrote {written} bytes against a declared {expected}"
        )

    partial.replace(destination)
    return written
