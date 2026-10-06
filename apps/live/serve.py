"""AgniNetra Live as one long running process: the app, and its feed through the evening.

Usage, from the repository root, after `npm run build` in `apps/live/web`:
    uv run python -m apps.live.serve
    uv run python -m apps.live.serve --no-build --port 4318

The built app is served from `apps/live/web/dist`. `/feed/` and `/social/` are served from
`data/`, which a deployment keeps on a persistent volume, so past evenings survive a
redeploy and Smog Wrapped can be rebuilt from them. The feed is rebuilt at RUN_TIMES_IST,
every thirty minutes from 16:37 to 21:37 IST, since INSAT granules arrive about an hour
after acquisition, plus 23:37 for the day's final state, and once at start when there is
no feed yet. Each build is its own process under a time limit, so a stalled download
cannot take the site down with it. Credentials come from the environment, D140.

No request is logged. A visitor's address is personal data, and rule 6 keeps personal
data off the server.
"""

import argparse
import gzip
import html
import mimetypes
import os
import subprocess
import sys
import threading
import time
import urllib.parse
from datetime import datetime, timedelta
from datetime import time as clock
from email.utils import formatdate, parsedate_to_datetime
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from ml.paths import DATA_DIR, ROOT

from .pipeline.feed import IST

DIST = ROOT / "apps" / "live" / "web" / "dist"
FEED_DIR = DATA_DIR / "live" / "feed"
SOCIAL_DIR = DATA_DIR / "live_social"
ROUTES: tuple[tuple[str, Path], ...] = (("/feed/", FEED_DIR), ("/social/", SOCIAL_DIR), ("/", DIST))
LISTED = (SOCIAL_DIR,)
RUN_TIMES_IST = (
    (16, 37),
    (17, 7),
    (17, 37),
    (18, 7),
    (18, 37),
    (19, 7),
    (19, 37),
    (20, 7),
    (20, 37),
    (21, 7),
    (21, 37),
    (23, 37),
)
BUILD_TIMEOUT_S = 25 * 60
DEFAULT_PORT = 3000
GZIP_MIN_BYTES = 1024
COMPRESSIBLE = ("text/", "application/json", "application/manifest+json", "image/svg+xml")

for kind, suffix in (
    ("text/javascript", ".js"),
    ("image/webp", ".webp"),
    ("application/manifest+json", ".webmanifest"),
    ("image/svg+xml", ".svg"),
):
    mimetypes.add_type(kind, suffix)


def log(message: str) -> None:
    print(f"{datetime.now(IST):%Y-%m-%d %H:%M:%S} IST  {message}", flush=True)


def next_run(now: datetime) -> datetime:
    """The first scheduled build strictly after `now`, in IST."""
    local = now.astimezone(IST)
    candidates = (
        datetime.combine(local.date() + timedelta(days=days), clock(hour, minute), tzinfo=IST)
        for days in (0, 1)
        for hour, minute in RUN_TIMES_IST
    )
    return min(at for at in candidates if at > local)


def resolve(url_path: str, routes: tuple[tuple[str, Path], ...]) -> Path | None:
    """The file or listable folder a request path names, or None for anything else.

    A path that escapes its route's folder, by `..` or by an encoded form of it, is None.
    """
    path = urllib.parse.unquote(urllib.parse.urlsplit(url_path).path)
    for prefix, root in routes:
        if path.startswith(prefix):
            base = root.resolve()
            target = (base / path[len(prefix) :]).resolve()
            if not target.is_relative_to(base):
                return None
            if target.is_dir():
                index = target / "index.html"
                if index.is_file():
                    return index
                return target if root in LISTED else None
            return target if target.is_file() else None
    return None


def cache_control(url_path: str) -> str:
    # Vite names every built asset by its content hash, so a changed file is a new URL.
    if url_path.startswith("/assets/"):
        return "public, max-age=31536000, immutable"
    return "no-cache"


def content_type(path: Path) -> str:
    kind = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    if kind.startswith("text/") or kind == "application/json":
        return f"{kind}; charset=utf-8"
    return kind


def listing(folder: Path) -> bytes:
    rows = []
    for entry in sorted(folder.iterdir()):
        name = entry.name + ("/" if entry.is_dir() else "")
        rows.append(f'<li><a href="{urllib.parse.quote(name)}">{html.escape(name)}</a></li>')
    page = (
        '<!doctype html><meta charset="utf-8"><meta name="viewport" '
        'content="width=device-width, initial-scale=1"><title>AgniNetra social kit</title>'
        f"<ul>{''.join(rows)}</ul>"
    )
    return page.encode()


_compressed: dict[Path, tuple[int, bytes]] = {}
_compressed_lock = threading.Lock()


def gzipped(path: Path, payload: bytes, modified_ns: int) -> bytes:
    with _compressed_lock:
        kept = _compressed.get(path)
        if kept and kept[0] == modified_ns:
            return kept[1]
    packed = gzip.compress(payload, compresslevel=6)
    with _compressed_lock:
        _compressed[path] = (modified_ns, packed)
    return packed


class Handler(BaseHTTPRequestHandler):
    server_version = "AgniNetraLive"
    sys_version = ""

    def log_message(self, format: str, *args: object) -> None:
        return

    def do_GET(self) -> None:
        self.respond(with_body=True)

    def do_HEAD(self) -> None:
        self.respond(with_body=False)

    def respond(self, *, with_body: bool) -> None:
        target = resolve(self.path, ROUTES)
        if target is None:
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        url_path = urllib.parse.urlsplit(self.path).path
        if target.is_dir():
            if not url_path.endswith("/"):
                self.send_response(HTTPStatus.MOVED_PERMANENTLY)
                self.send_header("Location", url_path + "/")
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
            self.send_payload(listing(target), "text/html; charset=utf-8", with_body)
            return
        stat = target.stat()
        since = self.headers.get("If-Modified-Since")
        if since and not_modified_since(since, stat.st_mtime):
            self.send_response(HTTPStatus.NOT_MODIFIED)
            self.send_header("Cache-Control", cache_control(url_path))
            self.end_headers()
            return
        payload = target.read_bytes()
        kind = content_type(target)
        encoding = None
        if (
            kind.startswith(COMPRESSIBLE)
            and len(payload) >= GZIP_MIN_BYTES
            and "gzip" in self.headers.get("Accept-Encoding", "")
        ):
            payload, encoding = gzipped(target, payload, stat.st_mtime_ns), "gzip"
        self.send_response(HTTPStatus.OK)
        self.send_header("Last-Modified", formatdate(stat.st_mtime, usegmt=True))
        self.send_header("Cache-Control", cache_control(url_path))
        self.send_header("Vary", "Accept-Encoding")
        if encoding:
            self.send_header("Content-Encoding", encoding)
        self.send_payload(payload, kind, with_body, headers_open=True)

    def send_payload(
        self, payload: bytes, kind: str, with_body: bool, *, headers_open: bool = False
    ) -> None:
        if not headers_open:
            self.send_response(HTTPStatus.OK)
            self.send_header("Cache-Control", "no-cache")
        self.send_header("Content-Type", kind)
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        if with_body:
            self.wfile.write(payload)


def not_modified_since(header: str, modified: float) -> bool:
    try:
        since = parsedate_to_datetime(header)
    except (TypeError, ValueError):
        return False
    return int(modified) <= int(since.timestamp())


def build_once() -> None:
    started = time.monotonic()
    log("feed build started")
    steps = (
        ["apps.live.pipeline.build_feed", "--drop-raw", "--out", str(FEED_DIR)],
        ["apps.live.pipeline.social_kit", "--feed", str(FEED_DIR / "latest.json")],
    )
    for step in steps:
        try:
            done = subprocess.run(
                [sys.executable, "-m", *step], cwd=ROOT, timeout=BUILD_TIMEOUT_S, check=False
            )
        except subprocess.TimeoutExpired:
            log(f"{step[0]} stopped after {BUILD_TIMEOUT_S} s; the last good feed stays up")
            return
        if done.returncode != 0:
            log(f"{step[0]} failed with exit code {done.returncode}; the last good feed stays up")
            return
    log(f"feed build finished in {time.monotonic() - started:.0f} s")


def run_schedule(stop: threading.Event) -> None:
    if not (FEED_DIR / "latest.json").exists():
        build_once()
    while not stop.is_set():
        at = next_run(datetime.now(IST))
        log(f"next feed build at {at:%Y-%m-%d %H:%M} IST")
        if stop.wait(max((at - datetime.now(IST)).total_seconds(), 0.0)):
            return
        build_once()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=int(os.environ.get("PORT", DEFAULT_PORT)))
    parser.add_argument("--no-build", action="store_true", help="serve only, never build")
    args = parser.parse_args()
    if not (DIST / "index.html").is_file():
        log(f"no built app in {DIST.relative_to(ROOT)}; run npm run build in apps/live/web")
        return 1
    FEED_DIR.mkdir(parents=True, exist_ok=True)
    if not args.no_build:
        threading.Thread(target=run_schedule, args=(threading.Event(),), daemon=True).start()
    server = ThreadingHTTPServer(("0.0.0.0", args.port), Handler)
    log(f"serving AgniNetra Live on port {args.port}")
    server.serve_forever()
    return 0


if __name__ == "__main__":
    sys.exit(main())
