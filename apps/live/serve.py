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
import json
import mimetypes
import os
import re
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

from .community import MAX_BODY, Community
from .pipeline.feed import IST

DIST = ROOT / "apps" / "live" / "web" / "dist"
COMMUNITY: Community | None = None
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


# The app's day switcher reaches back two evenings; one more allows for the hours after
# midnight before the new day's first build. Older evenings stay on the volume for Smog
# Wrapped's season file but are not served one by one.
FEED_DAYS_SERVED = 4
# Evenings before today the app's day switcher offers.
DAYS_BACK = 2
FEED_DAY = re.compile(r"(\d{4}-\d{2}-\d{2})\.json")
SECURITY_HEADERS = (
    ("X-Content-Type-Options", "nosniff"),
    ("Referrer-Policy", "no-referrer"),
    ("X-Frame-Options", "SAMEORIGIN"),
    ("Permissions-Policy", "geolocation=(self), camera=(), microphone=(), payment=()"),
    (
        "Content-Security-Policy",
        "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
        "img-src 'self' data: blob:; connect-src 'self'; base-uri 'none'; "
        "form-action 'none'; frame-ancestors 'self'",
    ),
)


def feed_file_served(name: str, today: datetime) -> bool:
    """Whether a file in the feed folder is served: the latest feed, the season, and the
    evenings of the last FEED_DAYS_SERVED days."""
    if name in ("latest.json", "season.json", "days.json"):
        return True
    match = FEED_DAY.fullmatch(name)
    if not match:
        return False
    recent = {str(today.date() - timedelta(days=k)) for k in range(FEED_DAYS_SERVED)}
    return match.group(1) in recent


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

    def end_headers(self) -> None:
        for name, value in SECURITY_HEADERS:
            self.send_header(name, value)
        super().end_headers()

    def do_GET(self) -> None:
        if self.path.startswith("/api/"):
            self.api()
            return
        self.respond(with_body=True)

    def do_POST(self) -> None:
        self.api()

    def do_PUT(self) -> None:
        self.api()

    def do_DELETE(self) -> None:
        self.api()

    def api(self) -> None:
        if COMMUNITY is None:
            status, reply = 503, {"error": "Community labelling is not switched on here."}
        else:
            length = int(self.headers.get("Content-Length") or 0)
            if length > MAX_BODY:
                status, reply = 413, {"error": "Request too large."}
            else:
                body = self.rfile.read(length) if length else b""
                # Behind the proxy the visitor's address is the first forwarded one. It is
                # used only to count requests for the rate limit, and never written down.
                forwarded = self.headers.get("X-Forwarded-For", "")
                ip = forwarded.split(",")[0].strip() or self.client_address[0]
                headers = {"authorization": self.headers.get("Authorization", "")}
                path = urllib.parse.urlsplit(self.path).path
                status, reply = COMMUNITY.handle(self.command, path, headers, body, ip)
        payload = json.dumps(reply).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        # Answers are per player; no cache between here and the browser may keep one.
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(payload)

    def do_HEAD(self) -> None:
        self.respond(with_body=False)

    def respond(self, *, with_body: bool) -> None:
        target = resolve(self.path, ROUTES)
        if (
            target is not None
            and target.parent == FEED_DIR.resolve()
            and not feed_file_served(target.name, datetime.now(IST))
        ):
            target = None
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
        self.end_headers()
        if with_body:
            self.wfile.write(payload)


def not_modified_since(header: str, modified: float) -> bool:
    try:
        since = parsedate_to_datetime(header)
    except (TypeError, ValueError):
        return False
    return int(modified) <= int(since.timestamp())


def build_once(day: str | None = None) -> None:
    """Build tonight's feed and social kit, or, given a past day, add that evening only."""
    started = time.monotonic()
    log(f"feed build started{f' for {day}' if day else ''}")
    feed = ["apps.live.pipeline.build_feed", "--drop-raw", "--out", str(FEED_DIR)]
    if day:
        steps = [[*feed, "--date", day, "--keep-latest"]]
    else:
        steps = [feed, ["apps.live.pipeline.social_kit", "--feed", str(FEED_DIR / "latest.json")]]
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


def missing_evenings(today: datetime) -> list[str]:
    """The evenings the day switcher offers before today that the volume does not hold."""
    days = [str(today.date() - timedelta(days=k)) for k in range(1, DAYS_BACK + 1)]
    return [day for day in days if not (FEED_DIR / f"{day}.json").exists()]


def run_schedule(stop: threading.Event) -> None:
    if not (FEED_DIR / "latest.json").exists():
        build_once()
    # A fresh volume holds only tonight, so the switcher's earlier evenings are built once.
    for day in missing_evenings(datetime.now(IST)):
        if stop.is_set():
            return
        build_once(day)
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
    global COMMUNITY
    client_id, secret = os.environ.get("GOOGLE_CLIENT_ID", ""), os.environ.get("QUALIFY_SECRET", "")
    if client_id and len(secret) >= 32:
        try:
            COMMUNITY = Community(client_id=client_id, secret=secret)
            log("community labelling on")
        except ValueError as exc:
            log(f"community labelling off: {exc}; QUALIFY_SECRET must match the pack's")
    else:
        log("community labelling off: GOOGLE_CLIENT_ID and QUALIFY_SECRET are not both set")
    if not args.no_build:
        threading.Thread(target=run_schedule, args=(threading.Event(),), daemon=True).start()
    server = ThreadingHTTPServer(("0.0.0.0", args.port), Handler)
    log(f"serving AgniNetra Live on port {args.port}")
    server.serve_forever()
    return 0


if __name__ == "__main__":
    sys.exit(main())
