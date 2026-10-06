"""Browser storage appears in one place only: the Live app's on-device store.

The console keeps nothing in the browser. AgniNetra Live keeps a player's own history,
streaks, Wrapped stats, Netu's progress and Swipe answers, on the phone and nowhere else,
by the owner's decision D139. All of it goes through one module, so checking that nothing
leaves the phone means reading one file. The exemption is by exact path, as ml/tracked.py
requires.
"""

import re

from ml.tracked import relative, tracked_files

STORAGE = re.compile(r"\b(localStorage|sessionStorage|indexedDB)\b")
STORE = "apps/live/web/src/store.ts"


def test_only_the_live_store_touches_browser_storage() -> None:
    users = [
        relative(path)
        for path in tracked_files((".ts", ".tsx", ".js", ".mjs"))
        if STORAGE.search(path.read_text(encoding="utf8"))
    ]
    assert [u for u in users if u != STORE] == []
