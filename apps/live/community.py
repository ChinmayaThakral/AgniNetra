"""Community labelling for AgniNetra Live: sign in, qualify, label, and keep game data in sync.

One SQLite file on the data volume and Python's standard library, nothing else.

A player signs in with Google. To label unidentified hot spots in Swipe they first
qualify: QUALIFY_NEEDED Heatle rounds solved within MAX_CLUES clues, on sites whose type a
registry confirms, dealt by the server one clue at a time, each site at most once per
player, so answers can neither be looked up nor memorised. The answers live here only as
HMACs under QUALIFY_SECRET, so the public repository does not give them away. A qualified
player's Swipe answers are kept one per site, the first one, so nobody can repeat or flip
a vote, and the eight verified sites are mixed in unannounced to measure each player's
eye. Final labels are decided offline from these answers, community_labels.py.

What is stored: the email Google confirms, qualifying progress, Swipe answers, and the
player's own game data, which then follows them across browsers. Sessions are kept only
as hashes. A player can delete all of it.
"""

import hashlib
import hmac
import json
import random
import secrets
import sqlite3
import threading
import time
import urllib.parse
import urllib.request
from collections import defaultdict, deque
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path

from ml.paths import DATA_DIR, ROOT

DB_PATH = DATA_DIR / "live" / "community.db"
PACK_PATH = ROOT / "apps" / "live" / "pipeline" / "qualify_pack.json"
SWIPE_PATH = ROOT / "apps" / "live" / "web" / "public" / "game" / "swipe.json"
TOKENINFO_URL = "https://oauth2.googleapis.com/tokeninfo"
GOOGLE_ISSUERS = ("accounts.google.com", "https://accounts.google.com")

QUALIFY_NEEDED = 50
MAX_CLUES = 4
SESSION_S = 30 * 24 * 3600
MAX_BODY = 64 * 1024
MAX_DATA = 48 * 1024
GOLD_EVERY = 5
ITEM_FIELDS = ("id", "chip", "acquired", "wide", "details")
SWIPE_ANSWERS = ("industry", "not industry", "unsure")
DATA_KEYS = ("pet", "heatle", "swipe", "visits", "city", "theme")
# Requests per minute: any API call per address, sign ins per address, writes per player.
LIMITS = {"ip": 120, "signin": 10, "write": 90}

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
  id INTEGER PRIMARY KEY,
  email TEXT NOT NULL UNIQUE,
  created TEXT NOT NULL,
  correct INTEGER NOT NULL DEFAULT 0,
  attempts INTEGER NOT NULL DEFAULT 0,
  qualified TEXT,
  data TEXT
);
CREATE TABLE IF NOT EXISTS sessions (
  token_hash TEXT PRIMARY KEY,
  user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  expires REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS rounds (
  id TEXT PRIMARY KEY,
  user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  puzzle TEXT NOT NULL,
  shown INTEGER NOT NULL,
  wrong INTEGER NOT NULL DEFAULT 0,
  status TEXT NOT NULL,
  UNIQUE (user_id, puzzle)
);
CREATE TABLE IF NOT EXISTS answers (
  user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  item TEXT NOT NULL,
  answer TEXT NOT NULL,
  kind TEXT,
  at TEXT NOT NULL,
  PRIMARY KEY (user_id, item)
);
"""


class ApiError(Exception):
    def __init__(self, status: int, message: str) -> None:
        super().__init__(message)
        self.status = status


def mac(secret: str, *parts: str) -> str:
    return hmac.new(secret.encode(), "|".join(parts).encode(), hashlib.sha256).hexdigest()


def google_claims(id_token: str) -> dict:
    """Ask Google to check a sign in token; its own endpoint verifies the signature."""
    url = f"{TOKENINFO_URL}?{urllib.parse.urlencode({'id_token': id_token})}"
    try:
        with urllib.request.urlopen(url, timeout=10) as response:
            return json.load(response)
    except (OSError, ValueError) as exc:
        raise ApiError(401, "Google did not accept this sign in.") from exc


def merge_data(stored: dict, incoming: dict) -> dict:
    """The same rule as the app's backup merge: keep both histories, the larger points."""
    out: dict = {}
    for key in ("heatle", "swipe", "visits"):
        a, b = stored.get(key) or {}, incoming.get(key) or {}
        if isinstance(a, dict) and isinstance(b, dict) and (a or b):
            out[key] = {**a, **b}
    xp = [
        d.get("pet", {}).get("xp", 0) for d in (stored, incoming) if isinstance(d.get("pet"), dict)
    ]
    if xp:
        out["pet"] = {"xp": max(int(x) for x in xp if isinstance(x, int | float))}
    for key in ("city", "theme"):
        value = incoming.get(key, stored.get(key))
        if isinstance(value, str) and len(value) <= 40:
            out[key] = value
    return out


class RateLimiter:
    def __init__(self, clock: Callable[[], float]) -> None:
        self.clock = clock
        self.hits: dict[str, deque] = defaultdict(deque)
        self.lock = threading.Lock()

    def check(self, kind: str, key: str) -> None:
        now = self.clock()
        with self.lock:
            hits = self.hits[f"{kind}:{key}"]
            while hits and hits[0] < now - 60:
                hits.popleft()
            if len(hits) >= LIMITS[kind]:
                raise ApiError(429, "Too many requests. Wait a minute and try again.")
            hits.append(now)


class Community:
    def __init__(
        self,
        *,
        client_id: str,
        secret: str,
        db_path: Path = DB_PATH,
        pack: dict | None = None,
        swipe: dict | None = None,
        verify: Callable[[str], dict] = google_claims,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self.client_id = client_id
        self.secret = secret
        self.verify = verify
        self.clock = clock
        self.pack = pack if pack is not None else json.loads(PACK_PATH.read_text())
        swipe = swipe if swipe is not None else json.loads(SWIPE_PATH.read_text())
        self.puzzles = {p["id"]: p for p in self.pack["puzzles"]}
        self.choices = list(self.pack["choices"])
        self.kinds = [c for c in self.choices if c != "cannot tell"]
        self.items = {i["id"]: i for i in swipe["items"] if i.get("community")}
        self.gold = {i for i in self.items if mac(secret, "gold", i) in set(self.pack["gold_macs"])}
        # A secret that differs from the one the pack was built with leaves every round
        # unanswerable; refusing to start says so at once instead of at the first guess.
        unresolved = [p for p in self.puzzles if not self.resolves(p)]
        if unresolved:
            raise ValueError(
                f"{len(unresolved)} qualifying rounds have no answer under this secret"
            )
        self.limits = RateLimiter(clock)
        self.lock = threading.Lock()
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(db_path, check_same_thread=False, isolation_level=None)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("PRAGMA foreign_keys=ON")
        self.db.executescript(SCHEMA)

    # -- plumbing ------------------------------------------------------------------------

    @contextmanager
    def transaction(self) -> Iterator[None]:
        self.db.execute("BEGIN IMMEDIATE")
        try:
            yield
        except BaseException:
            self.db.execute("ROLLBACK")
            raise
        self.db.execute("COMMIT")

    def handle(
        self, method: str, path: str, headers: dict, body: bytes, ip: str
    ) -> tuple[int, dict]:
        try:
            self.limits.check("ip", ip)
            route = (method, path)
            if route == ("GET", "/api/config"):
                return 200, self.config()
            payload = self.parse(body) if method in ("POST", "PUT") else {}
            if route == ("POST", "/api/session"):
                self.limits.check("signin", ip)
                return 200, self.sign_in(payload)
            user = self.user_for(headers.get("authorization", ""))
            if method != "GET":
                self.limits.check("write", str(user["id"]))
            handlers = {
                ("DELETE", "/api/session"): lambda: self.sign_out(headers),
                ("GET", "/api/me"): lambda: self.profile(user),
                ("DELETE", "/api/me"): lambda: self.delete(user),
                ("PUT", "/api/me/data"): lambda: self.sync(user, payload),
                ("POST", "/api/qualify/start"): lambda: self.start(user),
                ("POST", "/api/qualify/clue"): lambda: self.clue(user, payload),
                ("POST", "/api/qualify/guess"): lambda: self.guess(user, payload),
                ("GET", "/api/swipe/next"): lambda: self.next_item(user),
                ("POST", "/api/swipe/answer"): lambda: self.answer(user, payload),
            }
            if route not in handlers:
                raise ApiError(404, "No such API route.")
            return 200, handlers[route]()
        except ApiError as exc:
            return exc.status, {"error": str(exc)}

    @staticmethod
    def parse(body: bytes) -> dict:
        if len(body) > MAX_BODY:
            raise ApiError(413, "Request too large.")
        try:
            value = json.loads(body or b"{}")
        except ValueError as exc:
            raise ApiError(400, "Request is not JSON.") from exc
        if not isinstance(value, dict):
            raise ApiError(400, "Request must be a JSON object.")
        return value

    def now_iso(self) -> str:
        return datetime.fromtimestamp(self.clock(), UTC).isoformat(timespec="seconds")

    def config(self) -> dict:
        return {
            "client_id": self.client_id,
            "qualify_needed": QUALIFY_NEEDED,
            "max_clues": MAX_CLUES,
        }

    # -- accounts --------------------------------------------------------------------------

    def sign_in(self, payload: dict) -> dict:
        token, nonce = payload.get("id_token"), payload.get("nonce")
        if (
            not isinstance(token, str)
            or not isinstance(nonce, str)
            or len(token) > 4096
            or len(nonce) > 200
        ):
            raise ApiError(400, "A Google sign in token and nonce are needed.")
        claims = self.verify(token)
        if (
            claims.get("aud") != self.client_id
            or claims.get("iss") not in GOOGLE_ISSUERS
            or str(claims.get("email_verified")).lower() != "true"
            or float(claims.get("exp", 0)) < self.clock()
            or not hmac.compare_digest(str(claims.get("nonce", "")), nonce)
            or not isinstance(claims.get("email"), str)
        ):
            raise ApiError(401, "Google did not confirm this sign in.")
        email = claims["email"].strip().lower()
        session = secrets.token_urlsafe(32)
        with self.lock, self.transaction():
            self.db.execute(
                "INSERT INTO users (email, created) VALUES (?, ?) ON CONFLICT(email) DO NOTHING",
                (email, self.now_iso()),
            )
            user = self.db.execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()
            self.db.execute("DELETE FROM sessions WHERE expires < ?", (self.clock(),))
            self.db.execute(
                "INSERT INTO sessions VALUES (?, ?, ?)",
                (
                    hashlib.sha256(session.encode()).hexdigest(),
                    user["id"],
                    self.clock() + SESSION_S,
                ),
            )
        return {"token": session, **self.profile(user)}

    def user_for(self, header: str) -> sqlite3.Row:
        token = header[7:] if header.startswith("Bearer ") else ""
        if not token or len(token) > 100:
            raise ApiError(401, "Sign in first.")
        row = self.db.execute(
            "SELECT users.* FROM sessions JOIN users ON users.id = sessions.user_id "
            "WHERE token_hash = ? AND expires > ?",
            (hashlib.sha256(token.encode()).hexdigest(), self.clock()),
        ).fetchone()
        if row is None:
            raise ApiError(401, "Your sign in has expired. Sign in again.")
        return row

    def sign_out(self, headers: dict) -> dict:
        token = headers.get("authorization", "")[7:]
        self.db.execute(
            "DELETE FROM sessions WHERE token_hash = ?",
            (hashlib.sha256(token.encode()).hexdigest(),),
        )
        return {"ok": True}

    def profile(self, user: sqlite3.Row) -> dict:
        user = self.db.execute("SELECT * FROM users WHERE id = ?", (user["id"],)).fetchone()
        answered = self.db.execute(
            "SELECT count(*) FROM answers WHERE user_id = ?", (user["id"],)
        ).fetchone()[0]
        left = (
            len(self.puzzles)
            - self.db.execute(
                "SELECT count(*) FROM rounds WHERE user_id = ? AND status != 'open'", (user["id"],)
            ).fetchone()[0]
        )
        return {
            "email": user["email"],
            "correct": user["correct"],
            "attempts": user["attempts"],
            "qualified": user["qualified"] is not None,
            "rounds_left": left,
            "answered": answered,
            "data": json.loads(user["data"]) if user["data"] else None,
        }

    def delete(self, user: sqlite3.Row) -> dict:
        self.db.execute("DELETE FROM users WHERE id = ?", (user["id"],))
        return {"deleted": True}

    def sync(self, user: sqlite3.Row, payload: dict) -> dict:
        incoming = payload.get("data")
        if not isinstance(incoming, dict) or set(incoming) - set(DATA_KEYS):
            raise ApiError(400, "Game data has an unexpected shape.")
        with self.lock:
            stored = self.db.execute(
                "SELECT data FROM users WHERE id = ?", (user["id"],)
            ).fetchone()[0]
            merged = merge_data(json.loads(stored) if stored else {}, incoming)
            text = json.dumps(merged, separators=(",", ":"))
            if len(text) > MAX_DATA:
                raise ApiError(413, "Game data is too large to keep.")
            self.db.execute("UPDATE users SET data = ? WHERE id = ?", (text, user["id"]))
        return {"data": merged}

    # -- qualifying ------------------------------------------------------------------------

    def resolves(self, puzzle_id: str) -> bool:
        expected = self.puzzles[puzzle_id]["answer_mac"]
        return any(
            hmac.compare_digest(mac(self.secret, puzzle_id, c), expected) for c in self.choices
        )

    def answer_of(self, puzzle_id: str) -> str:
        expected = self.puzzles[puzzle_id]["answer_mac"]
        for choice in self.choices:
            if hmac.compare_digest(mac(self.secret, puzzle_id, choice), expected):
                return choice
        raise ApiError(500, "This puzzle has no answer under the configured secret.")

    def round_view(self, row: sqlite3.Row) -> dict:
        puzzle = self.puzzles[row["puzzle"]]
        return {
            "round": row["id"],
            "clues": puzzle["clues"][: row["shown"]],
            "total_clues": len(puzzle["clues"]),
            "choices": self.choices,
        }

    def start(self, user: sqlite3.Row) -> dict:
        if user["qualified"]:
            raise ApiError(409, "You have already qualified.")
        with self.lock:
            open_round = self.db.execute(
                "SELECT * FROM rounds WHERE user_id = ? AND status = 'open'", (user["id"],)
            ).fetchone()
            if open_round is not None:
                return self.round_view(open_round)
            used = {
                r[0]
                for r in self.db.execute(
                    "SELECT puzzle FROM rounds WHERE user_id = ?", (user["id"],)
                )
            }
            fresh = [p for p in self.puzzles if p not in used]
            if not fresh:
                raise ApiError(409, "You have played every qualifying site.")
            round_id = secrets.token_urlsafe(12)
            self.db.execute(
                "INSERT INTO rounds (id, user_id, puzzle, shown, status) "
                "VALUES (?, ?, ?, 1, 'open')",
                (round_id, user["id"], random.SystemRandom().choice(fresh)),
            )
            return self.round_view(
                self.db.execute("SELECT * FROM rounds WHERE id = ?", (round_id,)).fetchone()
            )

    def open_round(self, user: sqlite3.Row, payload: dict) -> sqlite3.Row:
        row = self.db.execute(
            "SELECT * FROM rounds WHERE id = ? AND user_id = ? AND status = 'open'",
            (str(payload.get("round", ""))[:40], user["id"]),
        ).fetchone()
        if row is None:
            raise ApiError(404, "That round is over or does not exist.")
        return row

    def clue(self, user: sqlite3.Row, payload: dict) -> dict:
        with self.lock:
            row = self.open_round(user, payload)
            total = len(self.puzzles[row["puzzle"]]["clues"])
            self.db.execute(
                "UPDATE rounds SET shown = min(shown + 1, ?) WHERE id = ?", (total, row["id"])
            )
            return self.round_view(
                self.db.execute("SELECT * FROM rounds WHERE id = ?", (row["id"],)).fetchone()
            )

    def guess(self, user: sqlite3.Row, payload: dict) -> dict:
        choice = payload.get("answer")
        if choice not in self.choices:
            raise ApiError(400, "Not one of the choices.")
        with self.lock:
            row = self.open_round(user, payload)
            puzzle = self.puzzles[row["puzzle"]]
            answer = self.answer_of(row["puzzle"])
            if choice == answer or row["shown"] >= len(puzzle["clues"]):
                right = choice == answer
                counted = right and row["shown"] <= MAX_CLUES
                with self.transaction():
                    self.db.execute(
                        "UPDATE rounds SET status = ?, wrong = wrong + ? WHERE id = ?",
                        ("solved" if right else "failed", 0 if right else 1, row["id"]),
                    )
                    self.db.execute(
                        "UPDATE users SET attempts = attempts + 1, correct = correct + ? "
                        "WHERE id = ?",
                        (1 if counted else 0, user["id"]),
                    )
                    self.db.execute(
                        "UPDATE users SET qualified = ? "
                        "WHERE id = ? AND qualified IS NULL AND correct >= ?",
                        (self.now_iso(), user["id"], QUALIFY_NEEDED),
                    )
                return {
                    "right": right,
                    "counted": counted,
                    "answer": answer,
                    "clues": puzzle["clues"],
                    **{k: v for k, v in self.profile(user).items() if k != "data"},
                }
            self.db.execute(
                "UPDATE rounds SET wrong = wrong + 1, shown = shown + 1 WHERE id = ?", (row["id"],)
            )
            view = self.round_view(
                self.db.execute("SELECT * FROM rounds WHERE id = ?", (row["id"],)).fetchone()
            )
            return {"right": False, **view}

    # -- labelling -------------------------------------------------------------------------

    def next_item(self, user: sqlite3.Row) -> dict:
        if not user["qualified"]:
            raise ApiError(403, "Qualify in Heatle first.")
        done = {
            r[0]
            for r in self.db.execute("SELECT item FROM answers WHERE user_id = ?", (user["id"],))
        }
        order = sorted(
            self.items, key=lambda i: hashlib.sha256(f"{user['id']}|{i}".encode()).hexdigest()
        )
        gold = [i for i in order if i in self.gold and i not in done]
        plain = [i for i in order if i not in self.gold and i not in done]
        if not gold and not plain:
            return {"item": None, "answered": len(done), "total": len(self.items)}
        pick = (
            gold[0]
            if gold and (len(done) % GOLD_EVERY == GOLD_EVERY - 1 or not plain)
            else plain[0]
        )
        item = self.items[pick]
        return {
            "item": {k: item[k] for k in ITEM_FIELDS if k in item},
            "kinds": self.kinds,
            "answered": len(done),
            "total": len(self.items),
        }

    def answer(self, user: sqlite3.Row, payload: dict) -> dict:
        if not user["qualified"]:
            raise ApiError(403, "Qualify in Heatle first.")
        item, choice, kind = payload.get("item"), payload.get("answer"), payload.get("kind")
        if item not in self.items or choice not in SWIPE_ANSWERS:
            raise ApiError(400, "Unknown site or answer.")
        if kind is not None and (choice != "industry" or kind not in self.kinds):
            raise ApiError(400, "A kind goes only with an industry answer, from the list.")
        inserted = self.db.execute(
            "INSERT OR IGNORE INTO answers (user_id, item, answer, kind, at) "
            "VALUES (?, ?, ?, ?, ?)",
            (user["id"], item, choice, kind, self.now_iso()),
        ).rowcount
        if not inserted:
            raise ApiError(409, "You have already answered this site.")
        return self.next_item(user)
