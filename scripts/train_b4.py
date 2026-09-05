"""Baseline B4. A linear probe on frozen TerraMind site embeddings.

Runs end to end from one Sentinel-2 L2A product: acquire, chip, embed, probe,
evaluate on the same spatially blocked groups as B1 and B2 under the D32 contract.

Support is measured before the probe is fitted, and a per class metric whose
support falls below the floor is printed as its support rather than as a number.
`scripts/b4_support.py` shows that one scene reaches 7 held out trained class
detections, so this script is expected to refuse most cells. That refusal is the
result, not a failure to run. D57.
"""

import os

# Pinned before any estimator library loads. Thread count changes the floating
# point reduction order inside sklearn's histogram builders, and random_state does
# not constrain it, so a fixed seed alone does not reproduce a fit. D59.
os.environ.setdefault("OMP_NUM_THREADS", "4")


import argparse
import json
import os
import sys
import zipfile
from datetime import UTC, datetime
from pathlib import Path

import duckdb
import numpy as np
from dotenv import load_dotenv
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import precision_recall_fscore_support

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ml.imagery.catalogue import search_l2a
from ml.imagery.cdse import (
    DownloadError,
    MissingCredentialsError,
    access_token,
    download_product,
)
from ml.imagery.chips import ChipError, band_paths_in_safe, read_chip
from ml.imagery.embed import embed_chips, load_backbone
from ml.labels.splits import HELD_OUT_GROUPS
from ml.paths import ARTIFACT_DIR, DUCKDB_PATH, ENV_PATH, RAW_DIR, ROOT, ensure_dir
from ml.reference.geo import GEO_MACROS

PROBE_LON = 82.6757
PROBE_LAT = 24.1030
WINDOW_START = datetime(2024, 10, 1, tzinfo=UTC)
WINDOW_END = datetime(2024, 12, 1, tzinfo=UTC)
TRAINED_CLASSES = ("flare", "industrial", "agricultural")
SEED = 20260905

# A per class F1 estimated on fewer than this many positives carries an interval
# that spans most of the unit range, so the number carries no information the
# support does not already give. Chosen before any metric was computed.
MIN_CLASS_SUPPORT = 30


def _extract_within(archive: Path, destination: Path) -> None:
    """Extract an archive, refusing any member that escapes the destination.

    The archive arrives from a remote API, so a crafted product with parent
    traversal or an absolute path in a member name would be a write primitive
    anywhere the process can reach.

    Note that `filter="data"`, the usual advice for this, is a `tarfile` parameter.
    `ZipFile.extractall` does not accept it and raises TypeError if given it. The
    protection here is the explicit resolve check: every member is resolved against
    the destination and refused if it lands outside, before anything is written.
    D69.
    """
    destination = destination.resolve()
    with zipfile.ZipFile(archive) as handle:
        for member in handle.namelist():
            target = (destination / member).resolve()
            if not target.is_relative_to(destination):
                raise DownloadError(
                    f"archive member {member!r} resolves outside the destination. "
                    "Refusing to extract."
                )
        handle.extractall(destination)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scene", help="product name, defaults to the least cloudy in the window")
    parser.add_argument("--keep-archive", action="store_true", help="do not delete the zip")
    return parser.parse_args()


def detections_in_scene(footprint_wkt: str) -> list[tuple]:
    connection = duckdb.connect()
    connection.execute("INSTALL spatial; LOAD spatial;")
    for macro in GEO_MACROS:
        connection.execute(macro)
    connection.execute(f"ATTACH '{DUCKDB_PATH}' AS a (READ_ONLY);")
    return connection.execute(
        """
        SELECT d.detection_id, d.longitude, d.latitude, c.state_name, c.weak_label
        FROM a.detections d JOIN a.detection_context c USING (detection_id)
        WHERE c.weak_label IN ('flare', 'industrial', 'agricultural')
          AND ST_Within(geo_point(d.longitude, d.latitude), ST_GeomFromText(?))
        """,
        [footprint_wkt],
    ).fetchall()


def main() -> int:
    args = parse_args()
    load_dotenv(ENV_PATH)

    products = search_l2a(PROBE_LON, PROBE_LAT, WINDOW_START, WINDOW_END)
    if args.scene:
        products = [p for p in products if p.name.startswith(args.scene)]
    if not products:
        print("BLOCKED: catalogue returned no matching product", file=sys.stderr)
        return 2
    scene = products[0]
    print(f"scene {scene.name}")
    print(f"cloud {scene.cloud_cover_pct:.4f} percent, {scene.size_gb:.2f} GB")

    rows = detections_in_scene(scene.footprint_wkt)
    membership = {s: g for g, states in HELD_OUT_GROUPS.items() for s in states}
    print(f"trained class detections inside the footprint: {len(rows)}")

    archive = ensure_dir(RAW_DIR / "sentinel2") / f"{scene.name}.zip"
    if not archive.exists():
        try:
            token = access_token(os.environ.get("CDSE_USERNAME"), os.environ.get("CDSE_PASSWORD"))
        except MissingCredentialsError as exc:
            print(f"BLOCKED: {exc}", file=sys.stderr)
            print(
                "Place CDSE_USERNAME and CDSE_PASSWORD in .env. The values are never read, "
                "printed or logged by this repository.",
                file=sys.stderr,
            )
            return 2
        print(f"downloading {scene.size_gb:.2f} GB")
        written = download_product(scene.product_id, token, archive)
        print(f"wrote {written} bytes")

    safe_root = archive.parent / f"{scene.name}"
    if not safe_root.exists():
        _extract_within(archive, archive.parent)
    bands = band_paths_in_safe(safe_root)
    print(f"bands located: {len(bands)}")

    chips, kept = [], []
    for detection_id, longitude, latitude, state, label in rows:
        try:
            chips.append(read_chip(bands, longitude, latitude))
        except ChipError:
            continue
        kept.append((detection_id, state, label))
    print(f"chips cut: {len(chips)} of {len(rows)}")
    if not chips:
        print("BLOCKED: no chip fitted inside the scene", file=sys.stderr)
        return 2

    model, torch = load_backbone()
    embeddings = embed_chips(model, torch, np.stack(chips))
    labels = np.array([label for _, _, label in kept])
    groups = np.array([membership.get(state, "train") for _, state, _ in kept])

    train_mask = groups == "train"
    if train_mask.sum() == 0 or len(set(labels[train_mask])) < 2:
        print("BLOCKED: the scene carries no usable training split", file=sys.stderr)
        return 2

    probe = LogisticRegression(max_iter=2000, random_state=SEED)
    probe.fit(embeddings[train_mask], labels[train_mask])

    report = {"scene": scene.name, "seed": SEED, "train_rows": int(train_mask.sum()), "groups": {}}
    print(f"\nprobe fitted on {int(train_mask.sum())} rows, seed {SEED}\n")
    for group in sorted(HELD_OUT_GROUPS):
        mask = groups == group
        entry: dict[str, object] = {"rows": int(mask.sum())}
        if mask.sum() == 0:
            print(f"{group}: no detections in this scene, B4 not evaluable here")
            report["groups"][group] = entry
            continue
        predicted = probe.predict(embeddings[mask])
        precision, recall, f1, support = precision_recall_fscore_support(
            labels[mask], predicted, labels=list(TRAINED_CLASSES), zero_division=0
        )
        for index, klass in enumerate(TRAINED_CLASSES):
            n = int(support[index])
            if n < MIN_CLASS_SUPPORT:
                entry[klass] = f"insufficient support, n={n}"
                print(f"{group} {klass}: insufficient support, n={n}")
            else:
                entry[klass] = {
                    "precision": round(float(precision[index]), 4),
                    "recall": round(float(recall[index]), 4),
                    "f1": round(float(f1[index]), 4),
                    "support": n,
                }
                print(
                    f"{group} {klass}: P {precision[index]:.3f} R {recall[index]:.3f} "
                    f"F1 {f1[index]:.3f} on n={n}"
                )
        report["groups"][group] = entry

    measured = any(
        isinstance(v, dict) for group in report["groups"].values() for v in group.values()
    )
    report["b4_status"] = "measured" if measured else "not measured, support below floor"
    destination = ensure_dir(ARTIFACT_DIR) / "b4_results.json"
    destination.write_text(json.dumps(report, indent=2, allow_nan=False))
    print(f"\nB4 status: {report['b4_status']}")
    print(f"wrote {destination.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
