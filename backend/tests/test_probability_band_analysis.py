"""Tests for probability / edge band analysis (ML-03)."""

from __future__ import annotations

import unittest

from backend.src.app.ml.training.probability_band_analysis import (
    BandAnalysisRecord,
    analyze_band_records,
    assign_edge_band,
    assign_probability_band,
    wilson_score_interval,
    _aggregate_records,
    _bucket_from_records,
)


def _record(
    prob: float,
    *,
    won: bool = True,
    edge: float | None = 5.0,
    odds: float = 2.0,
    fold: int | None = None,
    period: str = "2025-01",
) -> BandAnalysisRecord:
    profit = odds - 1.0 if won else -1.0
    return BandAnalysisRecord(
        match_date=None,
        fold_index=fold,
        model_version="v2",
        model_name="logistic_regression",
        prob_raw=prob,
        prob_used=prob,
        edge_pct=edge,
        odds=odds,
        won=won,
        profit=profit,
        period_key=period,
    )


class ProbabilityBandAnalysisTests(unittest.TestCase):
    def test_wilson_interval_midpoint_near_hit_rate(self) -> None:
        lower, upper = wilson_score_interval(60, 100)
        assert lower is not None and upper is not None
        self.assertGreater(lower, 50.0)
        self.assertLess(upper, 70.0)

    def test_assign_probability_band_edges(self) -> None:
        index, start, end = assign_probability_band(0.0, n_bins=10)
        self.assertEqual(index, 0)
        self.assertAlmostEqual(start, 0.0)
        self.assertAlmostEqual(end, 0.1)
        index, start, end = assign_probability_band(1.0, n_bins=10)
        self.assertEqual(index, 9)
        self.assertAlmostEqual(end, 1.0)

    def test_assign_edge_band_labels(self) -> None:
        key, label, _, _ = assign_edge_band(-1.0)
        self.assertEqual(key, "lt_0")
        self.assertIn("< 0%", label)
        key, _, _, _ = assign_edge_band(7.5)
        self.assertEqual(key, "5_10")

    def test_bucket_marks_insufficient_sample(self) -> None:
        records = [_record(0.55, won=True), _record(0.56, won=False)]
        bucket = _bucket_from_records(
            records,
            key="p_05",
            label="50% – 60%",
            start=0.5,
            end=0.6,
            min_bin_samples=30,
        )
        self.assertTrue(bucket.insufficient_sample)
        self.assertEqual(bucket.closed, 2)
        self.assertEqual(bucket.won, 1)
        self.assertEqual(bucket.lost, 1)
        self.assertAlmostEqual(bucket.hit_rate_pct or 0.0, 50.0)

    def test_aggregate_probability_bands_covers_all_bins(self) -> None:
        records = [
            _record(0.52, won=True),
            _record(0.78, won=False),
            _record(0.79, won=True),
        ]
        bands = _aggregate_records(records, band_dimension="probability", n_bins=10, min_bin_samples=1)
        self.assertEqual(len(bands), 10)
        non_empty = [item for item in bands if item.predictions_total > 0]
        self.assertEqual(len(non_empty), 2)

    def test_analyze_with_period_groups(self) -> None:
        records = [
            _record(0.6, won=True, period="2025-01"),
            _record(0.62, won=False, period="2025-02"),
        ]
        result = analyze_band_records(
            records,
            source="live",
            band_dimension="probability",
            n_bins=5,
            min_bin_samples=1,
            group_by_period=True,
        )
        self.assertEqual(len(result.by_period), 2)
        self.assertEqual(result.predictions_total, 2)

    def test_analyze_edge_dimension(self) -> None:
        records = [
            _record(0.6, won=True, edge=2.0),
            _record(0.65, won=True, edge=8.0),
        ]
        result = analyze_band_records(
            records,
            source="backtest",
            band_dimension="edge",
            n_bins=10,
            min_bin_samples=1,
        )
        keys = {item.key for item in result.bands if item.predictions_total > 0}
        self.assertIn("0_5", keys)
        self.assertIn("5_10", keys)


if __name__ == "__main__":
    unittest.main()
