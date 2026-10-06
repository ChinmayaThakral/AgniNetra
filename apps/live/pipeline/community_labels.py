"""Turn qualified players' Swipe answers into labels for the unidentified hot spots.

Usage, from the repository root, on the machine that holds the community database:
    uv run python -m apps.live.pipeline.community_labels [path/to/community.db]

Each player's eye is measured on the verified sites mixed into their queue unannounced.
All of those are industry, so a player's reliability is the share they called industry,
smoothed so that one lucky answer does not make anyone an oracle. A site is labelled only
when at least MIN_VOTERS qualified players gave a firm answer and their reliability
weighted agreement reaches AGREEMENT. Everything else stays unlabelled; an unsure answer
counts as no vote. The output is a review list, not ground truth: a label joins the
dataset only after someone checks it against imagery.
"""

import json
import os
import sqlite3
import sys
from collections import defaultdict
from pathlib import Path

from dotenv import load_dotenv

from ml.paths import DATA_DIR, ENV_PATH

from ..community import DB_PATH, PACK_PATH, SWIPE_PATH, mac

OUT = DATA_DIR / "live" / "community_labels.json"
MIN_VOTERS = 3
AGREEMENT = 0.75
PRIOR_RIGHT, PRIOR_SEEN = 1, 2


def reliability(right: int, seen: int) -> float:
    return (right + PRIOR_RIGHT) / (seen + PRIOR_SEEN)


def decide(answers: list[tuple[int, str, str | None]], gold: set[str], items: list[str]) -> dict:
    """answers are (user, item, answer, kind) rows; returns labels and per player weights."""
    right: dict[int, int] = defaultdict(int)
    seen: dict[int, int] = defaultdict(int)
    for user, item, answer, _ in answers:
        if item in gold and answer != "unsure":
            seen[user] += 1
            right[user] += answer == "industry"
    weight = {u: reliability(right[u], seen[u]) for u in {a[0] for a in answers}}

    votes: dict[str, list[tuple[int, str, str | None]]] = defaultdict(list)
    for user, item, answer, kind in answers:
        if item not in gold and answer != "unsure":
            votes[item].append((user, answer, kind))

    labels = []
    for item in items:
        if item in gold:
            continue
        cast = votes.get(item, [])
        if len(cast) < MIN_VOTERS:
            continue
        totals: dict[str, float] = defaultdict(float)
        for user, answer, _ in cast:
            totals[answer] += weight[user]
        top, top_weight = max(totals.items(), key=lambda kv: kv[1])
        share = top_weight / sum(totals.values())
        if share < AGREEMENT:
            continue
        label = {"item": item, "label": top, "agreement": round(share, 3), "voters": len(cast)}
        if top == "industry":
            kinds: dict[str, float] = defaultdict(float)
            for user, answer, kind in cast:
                if answer == "industry" and kind:
                    kinds[kind] += weight[user]
            if kinds:
                kind, kind_weight = max(kinds.items(), key=lambda kv: kv[1])
                if kind_weight / top_weight >= AGREEMENT:
                    label["kind"] = kind
        labels.append(label)
    return {"labels": labels, "players": len(weight)}


def main() -> int:
    load_dotenv(ENV_PATH)
    secret = os.environ.get("QUALIFY_SECRET", "")
    if len(secret) < 32:
        print("QUALIFY_SECRET is missing or short; it must match the server's", file=sys.stderr)
        return 1
    db_path = Path(sys.argv[1]) if len(sys.argv) > 1 else DB_PATH
    db = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    answers = db.execute("SELECT user_id, item, answer, kind FROM answers").fetchall()
    items = [i["id"] for i in json.loads(SWIPE_PATH.read_text())["items"] if i.get("community")]
    gold_macs = set(json.loads(PACK_PATH.read_text())["gold_macs"])
    gold = {i for i in items if mac(secret, "gold", i) in gold_macs}
    result = decide(answers, gold, items)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(result, indent=1) + "\n")
    print(
        f"{len(result['labels'])} of {len(items) - len(gold)} sites labelled "
        f"from {len(answers)} answers by {result['players']} players"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
