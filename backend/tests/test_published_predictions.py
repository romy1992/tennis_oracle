"""Tests for the immutable published-prediction ledger."""

from __future__ import annotations

from datetime import date, datetime, time, timedelta
from unittest.mock import patch

import pytest

from backend.src.app.schemas.published_prediction import (
    PublishedPredictionCorrection,
    PublishedPredictionCreate,
)
from backend.src.app.services.published_predictions import (
    PublishedPredictionError,
    compute_content_hash,
    correct_published_prediction,
    list_publication_versions,
    list_published_predictions,
    match_has_started,
    publish_prediction,
)
from backend.src.entity.next_fixture import NextFixture
from backend.src.entity.published_prediction import PublishedPrediction


def _future_fixture(db_session, *, event_key: int = 9001) -> NextFixture:
    row = NextFixture(
        event_key=event_key,
        event_date=date.today() + timedelta(days=2),
        event_time=time(15, 0),
        event_first_player="Player A",
        event_second_player="Player B",
        tournament_name="Test Open",
        event_status="Not Started",
        is_completed=False,
    )
    db_session.add(row)
    db_session.commit()
    return row


def _past_fixture(db_session, *, event_key: int = 9002) -> NextFixture:
    row = NextFixture(
        event_key=event_key,
        event_date=date.today() - timedelta(days=1),
        event_time=time(10, 0),
        event_first_player="Player C",
        event_second_player="Player D",
        tournament_name="Past Open",
        event_status="Finished",
        is_completed=True,
    )
    db_session.add(row)
    db_session.commit()
    return row


def _create_payload(**overrides) -> PublishedPredictionCreate:
    data = {
        "event_key": 9001,
        "selection": "Player A",
        "model_version": "v3",
        "model_name": "logistic_regression",
        "probability": 0.62,
        "odds": 1.85,
        "void_odds": 1.6129,
        "edge": 14.7,
        "unit_stake": 1.0,
        "publication_source": "admin_api",
        "initial_status": "published",
    }
    data.update(overrides)
    return PublishedPredictionCreate(**data)


def test_publish_creates_immutable_snapshot(db_session):
    _future_fixture(db_session)
    result = publish_prediction(db_session, _create_payload())

    assert result.content_version == 1
    assert result.previous_version_id is None
    assert result.is_latest is True
    assert len(result.content_hash) == 64
    assert result.player_1_name == "Player A"
    assert result.tournament_name == "Test Open"

    stored = db_session.get(PublishedPrediction, result.id)
    assert stored is not None
    assert stored.publication_id == result.publication_id


def test_content_hash_stable_for_same_payload():
    kwargs = dict(
        event_key=1,
        selection="A",
        model_version="v3",
        model_name="logistic_regression",
        probability=0.55,
        odds=2.0,
        void_odds=1.8181,
        edge=10.0,
        unit_stake=1.0,
        publication_source="admin_api",
        initial_status="published",
        content_version=1,
        publication_id="abc",
    )
    assert compute_content_hash(**kwargs) == compute_content_hash(**kwargs)


def test_correction_creates_new_version_linked_to_previous(db_session):
    _future_fixture(db_session)
    first = publish_prediction(db_session, _create_payload(probability=0.60, odds=1.9))
    second = correct_published_prediction(
        db_session,
        previous_id=first.id,
        payload=PublishedPredictionCorrection(
            probability=0.65,
            odds=1.8,
            edge=20.0,
            publication_source="admin_api",
        ),
    )

    assert second.publication_id == first.publication_id
    assert second.content_version == 2
    assert second.previous_version_id == first.id
    assert second.probability == 0.65
    assert second.content_hash != first.content_hash

    chain = list_publication_versions(db_session, first.publication_id)
    assert len(chain.items) == 2
    assert chain.items[0].id == first.id
    assert chain.items[1].is_latest is True

    # Original row unchanged (append-only)
    original = db_session.get(PublishedPrediction, first.id)
    assert original is not None
    assert original.probability == 0.60
    assert original.content_version == 1


def test_cannot_publish_or_correct_after_match_started(db_session):
    _past_fixture(db_session, event_key=9002)
    assert match_has_started(db_session, 9002) is True

    with pytest.raises(PublishedPredictionError) as exc:
        publish_prediction(db_session, _create_payload(event_key=9002))
    assert exc.value.status_code == 409

    _future_fixture(db_session, event_key=9003)
    first = publish_prediction(db_session, _create_payload(event_key=9003))

    # Force match started after publish
    with patch(
        "backend.src.app.services.published_predictions.match_has_started",
        return_value=True,
    ):
        with pytest.raises(PublishedPredictionError) as exc2:
            correct_published_prediction(
                db_session,
                previous_id=first.id,
                payload=PublishedPredictionCorrection(probability=0.7),
            )
        assert exc2.value.status_code == 409


def test_list_latest_only_and_api(client, auth_headers, db_session):
    _future_fixture(db_session, event_key=9100)
    first = publish_prediction(
        db_session,
        _create_payload(event_key=9100),
        published_at=datetime(2026, 7, 20, 12, 0, 0),
    )
    correct_published_prediction(
        db_session,
        previous_id=first.id,
        payload=PublishedPredictionCorrection(probability=0.7),
        published_at=datetime(2026, 7, 20, 13, 0, 0),
    )

    listed = list_published_predictions(db_session, event_key=9100, latest_only=True)
    assert listed.total == 1
    assert listed.items[0].content_version == 2

    all_versions = list_published_predictions(
        db_session, event_key=9100, latest_only=False
    )
    assert all_versions.total == 2

    response = client.get(
        "/api/published-predictions",
        params={"event_key": 9100, "latest_only": True},
        headers=auth_headers,
    )
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    assert body["items"][0]["content_version"] == 2

    create_resp = client.post(
        "/api/published-predictions",
        headers=auth_headers,
        json={
            "event_key": 9100,
            "selection": "Player B",
            "model_version": "v3",
            "model_name": "random_forest",
            "probability": 0.55,
            "odds": 2.1,
            "void_odds": 1.818,
            "edge": 5.0,
            "unit_stake": 1.0,
            "publication_source": "admin_api",
            "initial_status": "published",
        },
    )
    assert create_resp.status_code == 201
    created = create_resp.json()

    versions = client.get(
        f"/api/published-predictions/by-publication/{created['publication_id']}",
        headers=auth_headers,
    )
    assert versions.status_code == 200
    assert len(versions.json()["items"]) == 1

    correction = client.post(
        f"/api/published-predictions/{created['id']}/corrections",
        headers=auth_headers,
        json={"probability": 0.58, "publication_source": "admin_api"},
    )
    assert correction.status_code == 201
    assert correction.json()["content_version"] == 2
    assert correction.json()["previous_version_id"] == created["id"]


def test_api_requires_admin(client):
    response = client.get("/api/published-predictions")
    assert response.status_code in {401, 403}
