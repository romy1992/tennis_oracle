"""Tests for segment ROI analysis (ML-04)."""

from __future__ import annotations

import unittest

from backend.src.app.ml.training.segment_roi_analysis import (
    SegmentAnalysisRecord,
    analyze_segment_records,
    assign_favorite_role,
    assign_odds_band,
    _aggregate_segment_records,
    _segment_bucket_from_records,
)


def _record(
    *,
    surface: str = "Hard",
    tournament: str = "Demo Open",
    circuit: str = "ATP Singles",
    level: str = "A",
    round_name: str = "R32",
    odds: float = 2.0,
    won: bool = True,
    model_version: str = "v2",
    model_name: str = "logistic_regression",
    period: str = "2025-01",
    bookmaker: str | None = None,
) -> SegmentAnalysisRecord:
    profit = odds - 1.0 if won else -1.0
    odds_band_key, _ = assign_odds_band(odds)
    favorite_key, _ = assign_favorite_role(odds)
    return SegmentAnalysisRecord(
        match_date=None,
        fold_index=None,
        match_id=None,
        model_version=model_version,
        model_name=model_name,
        prob_used=0.6,
        edge_pct=5.0,
        odds=odds,
        won=won,
        profit=profit,
        period_key=period,
        surface=surface,
        tournament_name=tournament,
        circuit=circuit,
        level=level,
        round_name=round_name,
        favorite_role=favorite_key,
        odds_band=odds_band_key,
        bookmaker=bookmaker,
    )


class SegmentRoiAnalysisTests(unittest.TestCase):
    def test_assign_favorite_role_threshold(self) -> None:
        key, label = assign_favorite_role(1.8)
        self.assertEqual(key, "favorite")
        self.assertEqual(label, "Favorito")
        key, label = assign_favorite_role(2.5)
        self.assertEqual(key, "underdog")
        self.assertEqual(label, "Sfavorito")

    def test_assign_odds_band_labels(self) -> None:
        key, label = assign_odds_band(1.4)
        self.assertEqual(key, "lt_1_50")
        self.assertIn("1.50", label)
        key, _ = assign_odds_band(2.5)
        self.assertEqual(key, "2_00_3_00")

    def test_bucket_marks_insufficient_sample_and_drawdown(self) -> None:
        records = [
            _record(won=True, odds=2.0),
            _record(won=False, odds=2.0),
        ]
        bucket = _segment_bucket_from_records(
            records,
            key="hard",
            label="Hard",
            min_segment_samples=30,
        )
        self.assertTrue(bucket.insufficient_sample)
        self.assertEqual(bucket.closed, 2)
        self.assertAlmostEqual(bucket.hit_rate_pct or 0.0, 50.0)
        self.assertGreaterEqual(bucket.max_drawdown, 0.0)
        self.assertIsNotNone(bucket.roi_ci_lower_pct)

    def test_aggregate_by_surface(self) -> None:
        records = [
            _record(surface="Hard", won=True),
            _record(surface="Hard", won=False),
            _record(surface="Clay", won=True),
        ]
        segments = _aggregate_segment_records(
            records,
            segment_dimension="surface",
            min_segment_samples=1,
        )
        populated = [item for item in segments if item.closed > 0]
        self.assertEqual(len(populated), 2)
        hard = next(item for item in populated if item.key == "Hard")
        self.assertEqual(hard.closed, 2)
        self.assertAlmostEqual(hard.hit_rate_pct or 0.0, 50.0)

    def test_analyze_by_favorite_role(self) -> None:
        records = [
            _record(odds=1.7, won=True),
            _record(odds=3.0, won=False),
        ]
        result = analyze_segment_records(
            records,
            source="live",
            segment_dimension="favorite_role",
            min_segment_samples=1,
        )
        keys = {item.key for item in result.segments if item.closed > 0}
        self.assertIn("favorite", keys)
        self.assertIn("underdog", keys)

    def test_analyze_by_period_groups(self) -> None:
        records = [
            _record(period="2025-01", won=True),
            _record(period="2025-02", won=False),
        ]
        result = analyze_segment_records(
            records,
            source="backtest",
            segment_dimension="period",
            min_segment_samples=1,
            group_by_period=True,
        )
        self.assertEqual(len(result.by_period), 2)
        self.assertEqual(result.predictions_total, 2)
