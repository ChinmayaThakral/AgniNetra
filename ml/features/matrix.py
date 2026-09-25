"""The phase 4 feature matrix, and the variables deliberately excluded from it.

The exclusion is the important part. The weak label is a deterministic function of
the distance to the nearest flare, the distance to the nearest industrial asset and
the land cover class. Feeding any of those to a classifier trained on that label
would let it recover the rule exactly, and the reported score would measure
arithmetic rather than attribution.

`LEAKING_COLUMNS` names them. `scripts/train_b1.py` fits one model with them
included purely to demonstrate the effect, and that model is never evaluated as a
baseline.

Raw coordinates are also excluded. Under a spatially blocked protocol a held out
state contains coordinates the model has never seen, so latitude and longitude
cannot help it and can only encourage it to memorise belts that do not transfer.
"""

from typing import Final

from ml.labels.weak import weak_label_sql

# A missing recurrence row means the feature was not computed for that detection.
# It does not mean the location had zero prior detections. An earlier version wrote
# `coalesce(r.prior_count_90d, 0)`, which asserted the second, and because
# `detection_recurrence` had not been rebuilt after the seasonal ingest that
# fabricated a zero for 92.1 percent of training rows at a rate that differed by
# class. HistGradientBoosting handles NULL natively, so the honest value is passed
# through and the model is told the feature is missing rather than told it is zero.
# D61.

# Deterministic inputs to the weak label rule. Never features. D43.
LEAKING_COLUMNS: Final[tuple[str, ...]] = (
    "flare_m",
    "industrial_m",
    "gem_m_temporal",
    "landcover_code",
    "landcover_class",
    "weak_label",
    "label_source",
    "label_rule",
    "label_confidence",
)

# Excluded for transfer rather than for leakage.
GEOGRAPHIC_COLUMNS: Final[tuple[str, ...]] = ("latitude", "longitude", "state_name")

FEATURE_COLUMNS: Final[tuple[str, ...]] = (
    # Thermal properties of the detection itself
    "frp",
    "scan",
    "track",
    "bright_primary",
    "bright_secondary",
    "bright_ratio",
    "confidence_ordinal",
    # Temporal encodings, cyclic so midnight is adjacent to 23:00
    "hour_sin",
    "hour_cos",
    "doy_sin",
    "doy_cos",
    "is_night",
    # Self referential recurrence at the location
    "prior_count_90d",
    "prior_count_30d",
    "night_fraction_90d",
    "frp_variance_90d",
    "mean_gap_days",
    # Sensor family, because the two products have different footprints
    "is_viirs",
)

# The label comes from the one definition in ml/labels/weak.py rather than an inline
# copy. Six scripts had been reading a stored column that predates the wildfire
# withdrawal, while this file carried the only correct copy of the rule. D120.
FEATURE_SQL: Final[str] = f"""
SELECT
    d.detection_id,
    c.state_name,
    d.acq_date_ist,
    {weak_label_sql("c", "g")} AS weak_label,
    d.longitude, d.latitude,
    d.frp, d.scan, d.track,
    coalesce(d.bright_ti4, d.brightness) AS bright_primary,
    coalesce(d.bright_ti5, d.bright_t31) AS bright_secondary,
    coalesce(d.bright_ti4, d.brightness)
      / nullif(coalesce(d.bright_ti5, d.bright_t31), 0) AS bright_ratio,
    d.confidence_ordinal,
    sin(2 * pi() * d.acq_hour_ist / 24.0) AS hour_sin,
    cos(2 * pi() * d.acq_hour_ist / 24.0) AS hour_cos,
    sin(2 * pi() * CAST(strftime(d.acq_date_ist, '%j') AS INTEGER) / 366.0) AS doy_sin,
    cos(2 * pi() * CAST(strftime(d.acq_date_ist, '%j') AS INTEGER) / 366.0) AS doy_cos,
    CASE WHEN d.daynight = 'N' THEN 1 ELSE 0 END AS is_night,
    r.prior_count_90d,
    r.prior_count_30d,
    r.night_fraction_90d,
    r.frp_variance_90d,
    r.mean_gap_days,
    CASE WHEN d.family = 'viirs' THEN 1 ELSE 0 END AS is_viirs,
    c.flare_m, c.industrial_m, g.gem_m_temporal, c.landcover_code,
    bf.near_group_a, bf.near_group_b, bf.near_group_c
FROM detections d
JOIN detection_context c USING (detection_id)
LEFT JOIN detection_gem g USING (detection_id)
LEFT JOIN detection_recurrence r USING (detection_id)
LEFT JOIN detection_buffer bf USING (detection_id)
WHERE c.state_name IS NOT NULL
ORDER BY d.detection_id
"""

EXTERNAL_SQL: Final[str] = FEATURE_SQL.replace(
    "WHERE c.state_name IS NOT NULL", "WHERE c.state_name IS NULL"
)
