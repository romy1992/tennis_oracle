"""Retry / backoff / circuit breaker / metrics of the API-Tennis client.

File name contains ``test_request_api`` on purpose: conftest lets these tests
drive ``requests.get`` themselves (always mocked here, never real HTTP).
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from requests import exceptions as requests_exc

from backend.src.app.observability.metrics import get_metrics
from backend.src.utility import request_api as module
from backend.src.utility.request_api import (
    ApiTennisCircuitOpenError,
    ApiTennisHttpError,
    ApiTennisInvalidResponseError,
    ApiTennisNetworkError,
    ApiTennisTimeoutError,
)
from backend.src.utility.resilience import (
    STATE_CLOSED,
    STATE_HALF_OPEN,
    STATE_OPEN,
    CircuitBreaker,
    backoff_delay,
)


def _response(status_code: int = 200, payload=None, headers=None) -> MagicMock:
    response = MagicMock()
    response.status_code = status_code
    response.url = "https://api.example/tennis/"
    response.text = "body"
    response.headers = headers or {}
    response.json.return_value = payload if payload is not None else {"result": [{"event_key": "1"}]}
    return response


def _counter(name: str, **labels: str) -> float:
    total = 0.0
    for item in get_metrics().snapshot()["counters"]:
        if item["name"] == name and all(item["labels"].get(k) == v for k, v in labels.items()):
            total += item["value"]
    return total


@pytest.fixture()
def client(monkeypatch):
    monkeypatch.setattr(module, "API_KEY", "fake-key-not-real")
    monkeypatch.setattr(module, "BASE_URL", "https://api.example/tennis/")
    monkeypatch.setenv("API_TENNIS_MAX_RETRIES", "2")
    monkeypatch.setenv("API_TENNIS_RETRY_BACKOFF_SECONDS", "0.5")
    monkeypatch.setenv("API_TENNIS_RETRY_BACKOFF_MAX_SECONDS", "8")
    monkeypatch.setenv("API_TENNIS_CIRCUIT_FAILURE_THRESHOLD", "5")
    monkeypatch.setenv("API_TENNIS_CIRCUIT_RECOVERY_SECONDS", "60")
    sleeps: list[float] = []
    monkeypatch.setattr(module, "_sleep", sleeps.append)
    module.reset_circuit_breaker()
    with patch.object(module, "requests") as mock_requests:
        yield mock_requests, sleeps
    module.reset_circuit_breaker()


class TestBackoffDelay:
    def test_grows_exponentially_and_is_capped(self):
        low = [backoff_delay(n, base_seconds=1.0, max_seconds=4.0, rng=lambda: 0.0) for n in (1, 2, 3, 4, 5)]
        high = [backoff_delay(n, base_seconds=1.0, max_seconds=4.0, rng=lambda: 1.0) for n in (1, 2, 3, 4, 5)]
        assert low == [0.5, 1.0, 2.0, 2.0, 2.0]
        assert high == [1.0, 2.0, 4.0, 4.0, 4.0]

    def test_zero_base_disables_waiting(self):
        assert backoff_delay(3, base_seconds=0.0, max_seconds=8.0) == 0.0


class TestCircuitBreaker:
    def test_opens_after_threshold_then_half_open_then_closes(self):
        now = [0.0]
        breaker = CircuitBreaker(failure_threshold=3, recovery_seconds=10.0, clock=lambda: now[0])
        assert breaker.allow_request()
        assert breaker.record_failure() is False
        assert breaker.record_failure() is False
        assert breaker.record_failure() is True
        assert breaker.state == STATE_OPEN
        assert breaker.allow_request() is False
        assert breaker.seconds_until_retry() == 10.0

        now[0] = 10.0
        assert breaker.state == STATE_HALF_OPEN
        assert breaker.allow_request() is True
        assert breaker.allow_request() is False  # single probe
        breaker.record_success()
        assert breaker.state == STATE_CLOSED
        assert breaker.allow_request() is True

    def test_failed_probe_reopens(self):
        now = [0.0]
        breaker = CircuitBreaker(failure_threshold=1, recovery_seconds=5.0, clock=lambda: now[0])
        breaker.record_failure()
        now[0] = 5.0
        assert breaker.allow_request() is True
        breaker.record_failure()
        assert breaker.state == STATE_OPEN
        assert breaker.seconds_until_retry() == 5.0

    def test_success_resets_consecutive_failures(self):
        breaker = CircuitBreaker(failure_threshold=2, recovery_seconds=5.0)
        breaker.record_failure()
        breaker.record_success()
        breaker.record_failure()
        assert breaker.state == STATE_CLOSED

    def test_threshold_zero_disables(self):
        breaker = CircuitBreaker(failure_threshold=0, recovery_seconds=5.0)
        for _ in range(10):
            breaker.record_failure()
        assert breaker.allow_request() is True


class TestRetries:
    def test_timeout_then_success_is_retried(self, client):
        mock_requests, sleeps = client
        mock_requests.get.side_effect = [requests_exc.Timeout(), _response()]
        before = _counter(module.METRIC_RETRIES, method="get_fixtures", reason="timeout")

        assert module.request_api(method="get_fixtures") == [{"event_key": "1"}]

        assert mock_requests.get.call_count == 2
        assert len(sleeps) == 1 and 0.25 <= sleeps[0] <= 0.5
        assert _counter(module.METRIC_RETRIES, method="get_fixtures", reason="timeout") == before + 1

    def test_retries_are_bounded_and_keep_typed_error(self, client):
        mock_requests, sleeps = client
        mock_requests.get.side_effect = requests_exc.Timeout()

        with pytest.raises(ApiTennisTimeoutError):
            module.request_api(method="get_fixtures")

        assert mock_requests.get.call_count == 3
        assert len(sleeps) == 2
        assert 0.25 <= sleeps[0] <= 0.5 and 0.5 <= sleeps[1] <= 1.0

    def test_connection_error_is_retried(self, client):
        mock_requests, _ = client
        mock_requests.get.side_effect = [requests_exc.ConnectionError(), _response()]
        assert module.request_api(method="get_odds") == [{"event_key": "1"}]
        assert mock_requests.get.call_count == 2

    @pytest.mark.parametrize("status", [429, 500, 502, 503, 504])
    def test_retryable_http_status(self, client, status):
        mock_requests, _ = client
        mock_requests.get.side_effect = [_response(status), _response()]
        assert module.request_api(method="get_fixtures") == [{"event_key": "1"}]
        assert mock_requests.get.call_count == 2

    @pytest.mark.parametrize("status", [400, 401, 403, 404])
    def test_client_errors_are_not_retried(self, client, status):
        mock_requests, sleeps = client
        mock_requests.get.return_value = _response(status)
        with pytest.raises(ApiTennisHttpError) as ctx:
            module.request_api(method="get_fixtures")
        assert ctx.value.status_code == status
        assert mock_requests.get.call_count == 1
        assert sleeps == []

    def test_retry_after_header_is_honoured_and_capped(self, client, monkeypatch):
        mock_requests, sleeps = client
        monkeypatch.setenv("API_TENNIS_RETRY_BACKOFF_MAX_SECONDS", "3")
        mock_requests.get.side_effect = [
            _response(429, headers={"Retry-After": "2"}),
            _response(429, headers={"Retry-After": "120"}),
            _response(),
        ]
        module.request_api(method="get_fixtures")
        assert sleeps == [2.0, 3.0]

    def test_provider_declared_error_is_not_retried(self, client):
        mock_requests, sleeps = client
        mock_requests.get.return_value = _response(payload={"result": "Maximum date range for odds is 7 days."})
        with pytest.raises(ApiTennisInvalidResponseError):
            module.request_api(method="get_fixtures")
        assert mock_requests.get.call_count == 1
        assert sleeps == []

    def test_invalid_json_is_not_retried(self, client):
        mock_requests, _ = client
        response = _response()
        response.json.side_effect = ValueError("bad json")
        mock_requests.get.return_value = response
        with pytest.raises(ApiTennisInvalidResponseError):
            module.request_api(method="get_fixtures")
        assert mock_requests.get.call_count == 1

    def test_max_retries_zero_restores_single_attempt(self, client, monkeypatch):
        mock_requests, sleeps = client
        monkeypatch.setenv("API_TENNIS_MAX_RETRIES", "0")
        mock_requests.get.side_effect = requests_exc.Timeout()
        with pytest.raises(ApiTennisTimeoutError):
            module.request_api(method="get_fixtures")
        assert mock_requests.get.call_count == 1
        assert sleeps == []

    def test_invalid_env_value_raises_safe_error(self, client, monkeypatch):
        monkeypatch.setenv("API_TENNIS_MAX_RETRIES", "many")
        with pytest.raises(module.ApiTennisError):
            module.request_api(method="get_fixtures")


class TestClientCircuitBreaker:
    def test_opens_and_fails_fast_without_calling_provider(self, client, monkeypatch):
        mock_requests, _ = client
        monkeypatch.setenv("API_TENNIS_CIRCUIT_FAILURE_THRESHOLD", "3")
        mock_requests.get.side_effect = requests_exc.ConnectionError()

        with pytest.raises(ApiTennisNetworkError):
            module.request_api(method="get_odds")
        assert mock_requests.get.call_count == 3  # 3 failed attempts open the breaker
        assert module.circuit_breaker_state() == STATE_OPEN

        rejected_before = _counter(module.METRIC_REQUESTS, method="get_odds", outcome="circuit_open")
        with pytest.raises(ApiTennisCircuitOpenError) as ctx:
            module.request_api(method="get_odds")
        assert mock_requests.get.call_count == 3  # provider not contacted
        assert ctx.value.retry_after_seconds > 0
        assert isinstance(ctx.value, ApiTennisNetworkError)
        assert _counter(module.METRIC_REQUESTS, method="get_odds", outcome="circuit_open") == rejected_before + 1

    def test_stops_retrying_as_soon_as_the_breaker_opens(self, client, monkeypatch):
        mock_requests, _ = client
        monkeypatch.setenv("API_TENNIS_CIRCUIT_FAILURE_THRESHOLD", "2")
        mock_requests.get.side_effect = requests_exc.Timeout()
        with pytest.raises(ApiTennisTimeoutError):
            module.request_api(method="get_fixtures")
        assert mock_requests.get.call_count == 2

    def test_half_open_probe_success_closes(self, client, monkeypatch):
        mock_requests, _ = client
        monkeypatch.setenv("API_TENNIS_CIRCUIT_FAILURE_THRESHOLD", "1")
        monkeypatch.setenv("API_TENNIS_CIRCUIT_RECOVERY_SECONDS", "30")
        mock_requests.get.side_effect = requests_exc.Timeout()
        with pytest.raises(ApiTennisTimeoutError):
            module.request_api(method="get_fixtures")
        assert module.circuit_breaker_state() == STATE_OPEN

        breaker = module._circuit_breaker()
        breaker._opened_at -= 31  # recovery window elapsed
        assert module.circuit_breaker_state() == STATE_HALF_OPEN
        mock_requests.get.side_effect = None
        mock_requests.get.return_value = _response()
        assert module.request_api(method="get_fixtures") == [{"event_key": "1"}]
        assert module.circuit_breaker_state() == STATE_CLOSED

    def test_client_errors_do_not_open_the_breaker(self, client, monkeypatch):
        mock_requests, _ = client
        monkeypatch.setenv("API_TENNIS_CIRCUIT_FAILURE_THRESHOLD", "2")
        mock_requests.get.return_value = _response(401)
        for _ in range(5):
            with pytest.raises(ApiTennisHttpError):
                module.request_api(method="get_fixtures")
        assert module.circuit_breaker_state() == STATE_CLOSED

    def test_unexpected_exception_releases_half_open_probe(self, client, monkeypatch):
        mock_requests, _ = client
        monkeypatch.setenv("API_TENNIS_CIRCUIT_FAILURE_THRESHOLD", "1")
        mock_requests.get.side_effect = requests_exc.Timeout()
        with pytest.raises(ApiTennisTimeoutError):
            module.request_api(method="get_fixtures")
        module._circuit_breaker()._opened_at -= 61

        mock_requests.get.side_effect = RuntimeError("boom")
        with pytest.raises(RuntimeError):
            module.request_api(method="get_fixtures")
        mock_requests.get.side_effect = None
        mock_requests.get.return_value = _response()
        assert module.request_api(method="get_fixtures") == [{"event_key": "1"}]


class TestMetrics:
    def test_success_and_latency_are_recorded(self, client):
        mock_requests, _ = client
        mock_requests.get.return_value = _response()
        before = _counter(module.METRIC_REQUESTS, method="get_standings", outcome="success")
        module.request_api(method="get_standings")
        assert _counter(module.METRIC_REQUESTS, method="get_standings", outcome="success") == before + 1
        histograms = [
            item
            for item in get_metrics().snapshot()["histograms"]
            if item["name"] == module.METRIC_DURATION and item["labels"].get("method") == "get_standings"
        ]
        assert histograms and histograms[0]["count"] >= 1

    def test_metrics_never_contain_the_api_key(self, client):
        mock_requests, _ = client
        mock_requests.get.return_value = _response()
        module.request_api(method="get_fixtures")
        assert "fake-key-not-real" not in get_metrics().render_prometheus()
