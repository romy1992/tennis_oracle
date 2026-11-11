"""A provider failure while fetching odds must not look like "no odds"."""

from __future__ import annotations

from unittest.mock import patch

from backend.src.service import import_next_fixtures as module
from backend.src.utility.request_api import ApiTennisTimeoutError


def _payload(event_key: int) -> dict:
    return {
        "event_key": event_key,
        "event_date": module.today_local().strftime("%Y-%m-%d"),
        "event_type_type": "Atp Singles",
        "event_first_player": "A",
        "first_player_key": 10,
        "event_second_player": "B",
        "second_player_key": 20,
    }


ODDS = {"Home/Away": {"Home": {"Book A": "1.80"}, "Away": {"Book A": "2.00"}}}


def test_fetch_odds_reports_failure_without_changing_return_value():
    failures: list[int] = []
    with patch.object(module, "request_api", side_effect=ApiTennisTimeoutError("timeout")):
        assert module.fetch_odds_for_match(77, failures=failures) is None
        assert module.fetch_odds_for_match(78) is None  # legacy call style still works
    assert failures == [77]


def test_fetch_odds_empty_is_not_a_failure():
    failures: list[int] = []
    with patch.object(module, "request_api", return_value=[]):
        assert module.fetch_odds_for_match(77, failures=failures) is None
    assert failures == []


def test_import_summary_separates_fetched_empty_and_failed_odds():
    def fake_request_api(method, params=None, **_kwargs):
        if method == "get_fixtures":
            if params["date_start"] == module.today_local().strftime("%Y-%m-%d") and not fake_request_api.served:
                fake_request_api.served = True
                return [_payload(1), _payload(2), _payload(3)]
            return []
        match_key = params["match_key"]
        if match_key == 1:
            return ODDS
        if match_key == 2:
            return []
        raise ApiTennisTimeoutError("timeout")

    fake_request_api.served = False

    with patch.object(module, "request_api", side_effect=fake_request_api), patch.object(
        module, "next_fixtures_repo"
    ) as repo, patch.object(module, "_capture_prematch_odds_history"):
        repo.search_filter.return_value = []
        repo.delete_outside_date_range.return_value = 0
        repo.delete_completed.return_value = 0
        summary = module.import_next_fixtures(days_forward=3, days_back=0, import_odds=True)

    assert summary["inserted"] == 3
    assert summary["odds_fetched"] == 1
    assert summary["odds_empty"] == 1
    assert summary["odds_fetch_errors"] == 1


def test_import_without_odds_reports_zero_counters():
    with patch.object(module, "request_api", side_effect=[[_payload(5)], []]), patch.object(
        module, "next_fixtures_repo"
    ) as repo:
        repo.search_filter.return_value = []
        repo.delete_outside_date_range.return_value = 0
        repo.delete_completed.return_value = 0
        summary = module.import_next_fixtures(days_forward=3, days_back=0, import_odds=False)

    assert (summary["odds_fetched"], summary["odds_empty"], summary["odds_fetch_errors"]) == (0, 0, 0)
