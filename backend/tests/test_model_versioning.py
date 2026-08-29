from pathlib import Path

from backend.src.app.ml.model_versioning import select_training_dataset_path


V3_DATASET = "tennis_winner_dataset_with_odds_v3.csv"


def test_select_training_dataset_supports_gzip_fallback(tmp_path: Path):
    compressed = tmp_path / f"{V3_DATASET}.gz"
    compressed.write_bytes(b"gzip-placeholder")

    selected = select_training_dataset_path(tmp_path, version="v4")

    assert selected == compressed


def test_select_training_dataset_prefers_plain_csv(tmp_path: Path):
    plain = tmp_path / V3_DATASET
    compressed = tmp_path / f"{V3_DATASET}.gz"
    plain.write_text("plain", encoding="utf-8")
    compressed.write_bytes(b"gzip-placeholder")

    selected = select_training_dataset_path(tmp_path, version="v4")

    assert selected == plain
