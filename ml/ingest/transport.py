"""The real HTTP transport. Kept apart from the client so tests never import requests."""

import requests

from ml.ingest.firms import Response

DEFAULT_TIMEOUT_SECONDS = 120


class RequestsTransport:
    """Transport backed by requests."""

    def __init__(self, timeout: int = DEFAULT_TIMEOUT_SECONDS) -> None:
        self._timeout = timeout

    def get(self, url: str) -> Response:
        reply = requests.get(url, timeout=self._timeout)
        return Response(status=reply.status_code, text=reply.text)
