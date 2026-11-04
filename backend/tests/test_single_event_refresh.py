from datetime import date

import pytest
from sqlalchemy.orm import Session

from backend.src.app.services import single_event_refresh as svc
from backend.src.entity import NextFixture


class _Combo:
    def __init__(self, version: str, name: str) -> None:
        self.model_version = version
        self.model_name = name


def _payload(event_key: int = 10, **extra) -> dict:
    return {"event_key": event_key, "event_type_type": "Atp Singles", **extra}


def _patch_common(monkeypatch, *, payloads, active_run=None, completed=False, combos=()):
    monkeypatch.setattr(svc, "request_api", lambda **kwargs: payloads)
    monkeypatch.setattr(svc, "is_match_completed", lambda payload: completed)
    monkeypatch.setattr(
        "backend.src.app.services.global_update.get_active_run", lambda db: active_run
    )
    monkeypatch.setattr(
        "backend.src.app.services.global_update.list_enabled_combinations", lambda: list(combos)
    )

    def fake_ingest(items, summary, *, import_odds):
        summary["updated"] += len(items)

    monkeypatch.setattr(svc, "_ingest_upcoming_payloads", fake_ingest)


def test_unknown_event_is_not_found(db_session: Session, monkeypatch) -> None:
    _patch_common(monkeypatch, payloads=[])
    assert svc.refresh_single_event(db_session, 10) == {"found": False, "event_key": 10}


def test_other_event_in_response_is_ignored(db_session: Session, monkeypatch) -> None:
    _patch_common(monkeypatch, payloads=[_payload(99)])
    assert svc.refresh_single_event(db_session, 10)["found"] is False


def test_global_update_running_blocks_refresh(db_session: Session, monkeypatch) -> None:
    _patch_common(monkeypatch, payloads=[_payload()], active_run=object())
    with pytest.raises(svc.SingleEventRefreshBusy):
        svc.refresh_single_event(db_session, 10)


def test_completed_match_updates_result_without_regenerating_predictions(
    db_session: Session, monkeypatch
) -> None:
    _patch_common(monkeypatch, payloads=[_payload()], completed=True, combos=[_Combo("v4", "voting")])
    monkeypatch.setattr(
        svc, "predict_upcoming_fixtures", lambda **kw: pytest.fail("non deve rigenerare")
    )

    result = svc.refresh_single_event(db_session, 10)

    assert result["found"] is True
    assert result["completed"] is True
    assert result["import"] == {"updated": 1}
    assert result["predictions"] == {}


def test_upcoming_match_regenerates_winner_and_extra_markets(db_session: Session, monkeypatch) -> None:
    db_session.add(
        NextFixture(
            event_key=10,
            event_date=date.today(),
            event_first_player="A",
            event_second_player="B",
            is_completed=False,
        )
    )
    db_session.commit()
    _patch_common(
        monkeypatch,
        payloads=[_payload()],
        combos=[_Combo("v4", "voting"), _Combo("v2", "random_forest")],
    )
    calls: list[tuple[str, str]] = []

    def fake_predict(db, fixtures, model_version, model_name, **kw):
        calls.append((model_version, model_name))
        return [{"event_key": f.event_key} for f in fixtures]

    monkeypatch.setattr(svc, "predict_upcoming_fixtures", fake_predict)
    monkeypatch.setattr(svc.PreMatchFeatureBuilder, "from_db", classmethod(lambda cls, db, **kw: object()))
    monkeypatch.setattr(
        svc,
        "EXTRA_MARKET_PREDICTORS",
        ((lambda fixture, feature_builder: {"market": "first_set_winner"}, "first_set_winner"),),
    )
    monkeypatch.setattr(
        svc, "_publish_result", lambda db, fixture, extra, **kw: "published"
    )

    result = svc.refresh_single_event(db_session, 10)

    assert result["completed"] is False
    assert calls == [("v4", "voting"), ("v2", "random_forest")]
    assert result["predictions"] == {"v4/voting": 1, "v2/random_forest": 1}
    assert result["extra_markets"] == {"first_set_winner": "published"}
    assert result["errors"] == {}


def test_one_failing_model_does_not_block_the_others(db_session: Session, monkeypatch) -> None:
    db_session.add(NextFixture(event_key=10, event_date=date.today(), is_completed=False))
    db_session.commit()
    _patch_common(monkeypatch, payloads=[_payload()], combos=[_Combo("v4", "voting"), _Combo("v2", "rf")])

    def fake_predict(db, fixtures, model_version, model_name, **kw):
        if model_version == "v4":
            raise RuntimeError("modello rotto")
        return [{}]

    monkeypatch.setattr(svc, "predict_upcoming_fixtures", fake_predict)
    monkeypatch.setattr(svc.PreMatchFeatureBuilder, "from_db", classmethod(lambda cls, db, **kw: object()))
    monkeypatch.setattr(svc, "EXTRA_MARKET_PREDICTORS", ())

    result = svc.refresh_single_event(db_session, 10)

    assert result["predictions"] == {"v2/rf": 1}
    assert "modello rotto" in result["errors"]["v4/voting"]
