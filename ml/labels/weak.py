"""Weak label rules, with per label provenance and confidence.

No detection is hand labelled. Labels come from spatial joins against the
reference layers, and those layers are incomplete non randomly, so every label
carries the rule that produced it, the layer it came from, and a confidence.

The unlabelled class is not a failure mode, it is the majority case and it is what
the positive unlabeled treatment in phase 6 consumes. A rule that labels most
detections is capturing geography, not source type. `assert_label_share` enforces
a ceiling on that.

Distances are in metres and come from the geo macros. Nothing here calls a
spherical function directly. D10.
"""

from dataclasses import dataclass
from typing import Final

CLASS_FLARE: Final[str] = "flare"
CLASS_INDUSTRIAL: Final[str] = "industrial"
CLASS_AGRICULTURAL: Final[str] = "agricultural"
CLASS_WILDFIRE: Final[str] = "wildfire"
CLASS_UNLABELLED: Final[str] = "unlabelled"

# Classes a baseline is trained on. Wildfire is deliberately absent: no weak label
# rule produces it any more, so the baselines structurally cannot recover it. That
# is a stated limitation and the motivation for the temporal model, not an
# oversight. D33.
TRAINED_CLASSES: Final[tuple[str, ...]] = (
    CLASS_FLARE,
    CLASS_INDUSTRIAL,
    CLASS_AGRICULTURAL,
)

CLASSES: Final[tuple[str, ...]] = (
    CLASS_FLARE,
    CLASS_INDUSTRIAL,
    CLASS_AGRICULTURAL,
    CLASS_WILDFIRE,
    CLASS_UNLABELLED,
)

# Radii are the one tuned family of numbers in this module, so each is stated with
# its reason and the sensitivity is reported rather than the tuned value alone.
FLARE_RADIUS_M: Final[float] = 500.0
INDUSTRIAL_RADIUS_M: Final[float] = 1000.0

# A rule that assigns one class to more than this share of detections is capturing
# geography rather than source type, and the run stops.
MAX_CLASS_SHARE: Final[float] = 0.60


class LabelShareError(RuntimeError):
    """Raised when one weak label class dominates the dataset."""


@dataclass(frozen=True)
class WeakLabel:
    """One weak label with the evidence that produced it."""

    label: str
    source: str
    rule: str
    confidence: float

    def __post_init__(self) -> None:
        if self.label not in CLASSES:
            raise ValueError(f"unknown class {self.label!r}")
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError(f"confidence out of range 0 to 1: {self.confidence}")


UNLABELLED: Final[WeakLabel] = WeakLabel(
    label=CLASS_UNLABELLED,
    source="none",
    rule="no reference layer matched within its radius",
    confidence=0.0,
)


def label_from_distances(
    flare_m: float | None,
    industrial_m: float | None,
    landcover_class: str | None,
    *,
    gem_m: float | None = None,
) -> WeakLabel:
    """Assign a weak label from the reference distances at one detection.

    Order matters and is deliberate. A flare catalogue entry is the strongest
    evidence available, because the catalogue is built from a physical
    discriminator rather than from a land use tag, so it is tested first. An
    industrial polygon is next. Land cover alone is the weakest and yields a lower
    confidence, because cropland says where a fire is, not what it is.
    """
    if flare_m is not None and flare_m <= FLARE_RADIUS_M:
        return WeakLabel(
            label=CLASS_FLARE,
            source="eog_flares",
            rule=f"within {FLARE_RADIUS_M:.0f} m of a catalogued flare site",
            confidence=0.9,
        )
    if industrial_m is not None and industrial_m <= INDUSTRIAL_RADIUS_M:
        return WeakLabel(
            label=CLASS_INDUSTRIAL,
            source="osm_industrial",
            rule=f"within {INDUSTRIAL_RADIUS_M:.0f} m of an OSM industrial feature",
            confidence=0.7,
        )
    # The GEM term the label of record carries. Without it this function was a third
    # definition of the rule that disagreed with the one B1 trains on. It is keyword
    # only and optional so the stored build path keeps its meaning, and so that this
    # function can serve as the independent second implementation `weak_label_sql` is
    # checked against. D121.
    if gem_m is not None and gem_m <= INDUSTRIAL_RADIUS_M:
        return WeakLabel(
            label=CLASS_INDUSTRIAL,
            source="gem_assets",
            rule=f"within {INDUSTRIAL_RADIUS_M:.0f} m of a GEM asset operating that year",
            confidence=0.7,
        )
    if landcover_class == "cropland":
        return WeakLabel(
            label=CLASS_AGRICULTURAL,
            source="esa_worldcover",
            rule="land cover is cropland and no industrial reference matched",
            confidence=0.5,
        )
    if landcover_class in ("tree_cover", "shrubland", "grassland"):
        # Vegetated land cover with nothing else matching was a wildfire label
        # until 2026-09-04. It is now unlabelled, and the rule is kept here rather
        # than deleted so the reason stays attached to the code.
        #
        # Measured lift against a uniformly placed detection inside India: 0.78x in
        # monsoon, 0.20x in the 2023 burning season, 0.17x after the GEM assets
        # were added. Below 1 in every window and worst where fire is most common.
        # That is anti correlated, not weak. Training on it and reporting recall
        # would measure agreement with a rule proven to point the wrong way.
        #
        # The cause is compositional: the rule fires only where nothing else
        # matched, so it is a residue rather than a class. Land cover cannot
        # separate a wildfire from stubble burning because both occur on
        # vegetation. D33.
        return WeakLabel(
            label=CLASS_UNLABELLED,
            source="esa_worldcover",
            rule=(
                "vegetated land cover with no industrial or flare match, formerly "
                "the wildfire rule, now unlabelled: measured lift below 1 in every "
                "window. D33"
            ),
            confidence=0.0,
        )
    return UNLABELLED


def class_shares(labels: list[WeakLabel]) -> dict[str, float]:
    """Return the share of each class. Shares sum to 1 over a non empty input."""
    if not labels:
        return dict.fromkeys(CLASSES, 0.0)
    counts = dict.fromkeys(CLASSES, 0)
    for weak_label in labels:
        counts[weak_label.label] += 1
    return {name: count / len(labels) for name, count in counts.items()}


def assert_label_share(
    labels: list[WeakLabel], ceiling: float = MAX_CLASS_SHARE
) -> dict[str, float]:
    """Return the class shares, raising if any labelled class exceeds the ceiling.

    The unlabelled class is exempt. A large unlabelled share is expected and is
    the input to the positive unlabeled treatment; a large share of any single
    labelled class is the warning sign.
    """
    shares = class_shares(labels)
    for name, share in shares.items():
        if name == CLASS_UNLABELLED:
            continue
        if share > ceiling:
            raise LabelShareError(
                f"class {name} holds {share:.1%} of detections, above the {ceiling:.0%} "
                "ceiling. A rule this dominant is capturing geography rather than "
                "source type. Check the radius before trusting any downstream number."
            )
    return shares


def weak_label_sql(context: str = "c", gem: str = "g", *, with_gem: bool = True) -> str:
    """The weak label as a SQL expression, the definition every analysis uses.

    There were three definitions and they disagreed. The column stored in
    `detection_context` was built before the wildfire rule was withdrawn on
    2026-09-04 and never rebuilt, so it still labels 79136 rows `wildfire` and differs
    from the rule B1 trains on in 74742 of 469430 labelled rows. `label_from_distances`
    above has no GEM term. The expression B1 used, inline in `FEATURE_SQL`, was the
    only one with both corrections, and six scripts were reading the stale column
    instead of it. D120.

    Written without a substitution. `NULL <= 1000` is NULL, a CASE treats NULL as not
    true, and `NULL OR TRUE` is TRUE, so an absent distance simply fails to match.
    That is the same result the earlier sentinel form produced, which substituted a
    distance of a trillion metres for an absent one, verified row by row, without
    inventing the distance to get it.

    The caller must join `detection_context` as `context` and `detection_gem`, left
    joined, as `gem`.

    `with_gem=False` is a named variant, not a second definition. It drops the GEM term
    from the industrial rule and nothing else. It exists because M1 reverses between
    the two: GEM only industrial detections in Gujarat are 24.3 percent nocturnal
    against 68.8 for OSM sourced ones, and per cell summaries are dominated by them.
    The owner decided on 2026-09-23 to report M1 under both definitions. Everything
    that is not that comparison uses the default. D121.
    """
    industrial = f"{context}.industrial_m <= {INDUSTRIAL_RADIUS_M:.0f}"
    if with_gem:
        industrial += f" OR {gem}.gem_m_temporal <= {INDUSTRIAL_RADIUS_M:.0f}"
    return (
        "CASE "
        f"WHEN {context}.flare_m <= {FLARE_RADIUS_M:.0f} THEN '{CLASS_FLARE}' "
        f"WHEN {industrial} THEN '{CLASS_INDUSTRIAL}' "
        f"WHEN {context}.landcover_class = 'cropland' THEN '{CLASS_AGRICULTURAL}' "
        f"ELSE '{CLASS_UNLABELLED}' END"
    )
