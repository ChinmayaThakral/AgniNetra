"""Weak label rules: precedence, provenance, and the dominance ceiling."""

import pytest

from ml.labels.weak import (
    CLASS_AGRICULTURAL,
    CLASS_FLARE,
    CLASS_INDUSTRIAL,
    CLASS_UNLABELLED,
    CLASS_WILDFIRE,
    CLASSES,
    FLARE_RADIUS_M,
    INDUSTRIAL_RADIUS_M,
    TRAINED_CLASSES,
    LabelShareError,
    WeakLabel,
    assert_label_share,
    class_shares,
    label_from_distances,
)


class TestPrecedence:
    def test_flare_beats_industrial_when_both_match(self) -> None:
        """Flare sites sit inside industrial polygons, so precedence decides."""
        result = label_from_distances(flare_m=100.0, industrial_m=100.0, landcover_class=None)
        assert result.label == CLASS_FLARE
        assert result.source == "eog_flares"

    def test_industrial_beats_cropland(self) -> None:
        result = label_from_distances(flare_m=None, industrial_m=500.0, landcover_class="cropland")
        assert result.label == CLASS_INDUSTRIAL

    def test_cropland_when_nothing_industrial_matches(self) -> None:
        result = label_from_distances(flare_m=None, industrial_m=None, landcover_class="cropland")
        assert result.label == CLASS_AGRICULTURAL

    def test_vegetated_is_unlabelled_not_wildfire(self) -> None:
        """D33. The land cover wildfire rule measured 0.17x lift, anti correlated
        rather than weak, so it now yields unlabelled and carries zero confidence."""
        for cover in ("tree_cover", "shrubland", "grassland"):
            result = label_from_distances(None, None, cover)
            assert result.label == CLASS_UNLABELLED, cover
            assert result.confidence == 0.0
            assert "D33" in result.rule

    def test_no_rule_produces_wildfire_any_more(self) -> None:
        """The baselines structurally cannot recover wildfire. Stated, not implied."""
        probes = [
            (100.0, None, None),
            (None, 100.0, None),
            (None, None, "cropland"),
            (None, None, "tree_cover"),
            (None, None, "built_up"),
            (None, None, None),
        ]
        assert all(label_from_distances(*probe).label != CLASS_WILDFIRE for probe in probes)
        assert CLASS_WILDFIRE not in TRAINED_CLASSES

    def test_built_up_alone_is_unlabelled(self) -> None:
        """Built up land is not a source type. It must not become industrial."""
        assert label_from_distances(None, None, "built_up").label == CLASS_UNLABELLED

    def test_no_evidence_is_unlabelled_with_zero_confidence(self) -> None:
        result = label_from_distances(None, None, None)
        assert result.label == CLASS_UNLABELLED
        assert result.confidence == 0.0


class TestRadiusBoundaries:
    def test_exactly_at_the_flare_radius_is_inside(self) -> None:
        assert label_from_distances(FLARE_RADIUS_M, None, None).label == CLASS_FLARE

    def test_just_outside_the_flare_radius_is_not(self) -> None:
        assert label_from_distances(FLARE_RADIUS_M + 0.01, None, None).label == CLASS_UNLABELLED

    def test_exactly_at_the_industrial_radius_is_inside(self) -> None:
        result = label_from_distances(None, INDUSTRIAL_RADIUS_M, None)
        assert result.label == CLASS_INDUSTRIAL

    def test_just_outside_the_industrial_radius_is_not(self) -> None:
        result = label_from_distances(None, INDUSTRIAL_RADIUS_M + 0.01, None)
        assert result.label == CLASS_UNLABELLED


class TestProvenance:
    def test_every_label_carries_source_rule_and_confidence(self) -> None:
        cases = [
            label_from_distances(100.0, None, None),
            label_from_distances(None, 100.0, None),
            label_from_distances(None, None, "cropland"),
            label_from_distances(None, None, "tree_cover"),
            label_from_distances(None, None, None),
        ]
        for result in cases:
            assert result.source
            assert result.rule
            assert 0.0 <= result.confidence <= 1.0

    def test_confidence_orders_by_evidence_strength(self) -> None:
        flare = label_from_distances(100.0, None, None)
        industrial = label_from_distances(None, 100.0, None)
        cropland = label_from_distances(None, None, "cropland")
        wildfire = label_from_distances(None, None, "tree_cover")
        assert flare.confidence > industrial.confidence > cropland.confidence
        assert cropland.confidence > wildfire.confidence

    def test_unknown_class_is_refused(self) -> None:
        with pytest.raises(ValueError, match="unknown class"):
            WeakLabel(label="volcano", source="x", rule="y", confidence=0.5)

    def test_confidence_out_of_range_is_refused(self) -> None:
        with pytest.raises(ValueError, match="out of range"):
            WeakLabel(label=CLASS_FLARE, source="x", rule="y", confidence=1.4)


class TestShareCeiling:
    def test_shares_sum_to_one(self) -> None:
        labels = [label_from_distances(100.0, None, None) for _ in range(3)]
        labels += [label_from_distances(None, None, None) for _ in range(7)]
        assert sum(class_shares(labels).values()) == pytest.approx(1.0)

    def test_empty_input_gives_all_zero_not_a_crash(self) -> None:
        shares = class_shares([])
        assert set(shares) == set(CLASSES)
        assert all(value == 0.0 for value in shares.values())

    def test_a_dominant_labelled_class_raises(self) -> None:
        labels = [label_from_distances(None, 100.0, None) for _ in range(7)]
        labels += [label_from_distances(None, None, None) for _ in range(3)]
        with pytest.raises(LabelShareError, match="capturing geography"):
            assert_label_share(labels)

    def test_a_dominant_unlabelled_share_is_allowed(self) -> None:
        """Mostly unlabelled is the expected shape, not a failure."""
        labels = [label_from_distances(None, None, None) for _ in range(95)]
        labels += [label_from_distances(100.0, None, None) for _ in range(5)]
        shares = assert_label_share(labels)
        assert shares[CLASS_UNLABELLED] == pytest.approx(0.95)

    def test_ceiling_is_exclusive_at_exactly_the_limit(self) -> None:
        labels = [label_from_distances(None, 100.0, None) for _ in range(6)]
        labels += [label_from_distances(None, None, None) for _ in range(4)]
        assert assert_label_share(labels)[CLASS_INDUSTRIAL] == pytest.approx(0.6)
