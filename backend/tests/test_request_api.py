import logging
import unittest
from io import StringIO
from unittest.mock import MagicMock, patch

from requests import exceptions as requests_exc

from backend.src.utility import request_api as module
from backend.src.utility.request_api import (
    ApiTennisHttpError,
    ApiTennisInvalidResponseError,
    ApiTennisNetworkError,
    ApiTennisTimeoutError,
)
from backend.src.utility.sensitive_data import (
    REDACTED,
    sanitize_headers,
    sanitize_payload,
    sanitize_text,
    sanitize_url,
)


FAKE_API_KEY = "secret-test-api-key-DO-NOT-LEAK"


class SensitiveDataTest(unittest.TestCase):
    def test_sanitize_url_masks_apikey_query(self):
        url = f"https://api.example/tennis/?APIkey={FAKE_API_KEY}&method=get_fixtures"
        sanitized = sanitize_url(url)
        self.assertNotIn(FAKE_API_KEY, sanitized)
        self.assertIn(f"APIkey={REDACTED}", sanitized)
        self.assertIn("method=get_fixtures", sanitized)

    def test_sanitize_url_masks_db_password(self):
        url = "postgresql://postgres:s3cretPass@localhost:5432/tennis_db"
        sanitized = sanitize_url(url)
        self.assertNotIn("s3cretPass", sanitized)
        self.assertIn(f"postgres:{REDACTED}@", sanitized)

    def test_sanitize_headers_masks_authorization_and_cookie(self):
        headers = {
            "Authorization": "Bearer tok-123",
            "Cookie": "session=abc",
            "Content-Type": "application/json",
        }
        sanitized = sanitize_headers(headers)
        self.assertEqual(sanitized["Authorization"], REDACTED)
        self.assertEqual(sanitized["Cookie"], REDACTED)
        self.assertEqual(sanitized["Content-Type"], "application/json")

    def test_sanitize_payload_masks_nested_secrets(self):
        payload = {
            "method": "get_odds",
            "APIkey": FAKE_API_KEY,
            "nested": {"password": "p@ss", "token": "t-1", "ok": 1},
        }
        sanitized = sanitize_payload(payload)
        serialized = str(sanitized)
        self.assertNotIn(FAKE_API_KEY, serialized)
        self.assertNotIn("p@ss", serialized)
        self.assertNotIn("t-1", serialized)
        self.assertEqual(sanitized["APIkey"], REDACTED)
        self.assertEqual(sanitized["nested"]["password"], REDACTED)
        self.assertEqual(sanitized["nested"]["ok"], 1)

    def test_sanitize_text_masks_query_like_body(self):
        text = f"APIkey={FAKE_API_KEY}&method=get_fixtures"
        sanitized = sanitize_text(text)
        self.assertNotIn(FAKE_API_KEY, sanitized)


class RequestApiTest(unittest.TestCase):
    def setUp(self):
        self._prev_key = module.API_KEY
        self._prev_base = module.BASE_URL
        module.API_KEY = FAKE_API_KEY
        module.BASE_URL = "https://api.example/tennis/"

    def tearDown(self):
        module.API_KEY = self._prev_key
        module.BASE_URL = self._prev_base

    def _capture_logs(self):
        stream = StringIO()
        handler = logging.StreamHandler(stream)
        handler.setLevel(logging.DEBUG)
        logger = logging.getLogger(module.__name__)
        previous_level = logger.level
        logger.setLevel(logging.DEBUG)
        logger.addHandler(handler)
        return stream, handler, logger, previous_level

    def _release_logs(self, handler, logger, previous_level):
        logger.removeHandler(handler)
        logger.setLevel(previous_level)

    @patch.object(module, "requests")
    def test_raises_on_string_result(self, mock_requests):
        response = MagicMock()
        response.status_code = 200
        response.url = "https://example.test"
        response.json.return_value = {
            "result": "Maximum date range for odds is 7 days."
        }
        mock_requests.get.return_value = response

        with self.assertRaises(ApiTennisInvalidResponseError) as ctx:
            module.request_api(method="get_fixtures", params={"date_start": "2026-07-18"})
        self.assertIn("Maximum date range", str(ctx.exception))

    @patch.object(module, "requests")
    def test_raises_on_cod_error_list(self, mock_requests):
        response = MagicMock()
        response.status_code = 200
        response.url = "https://example.test"
        response.json.return_value = {
            "result": [{"cod": "404", "msg": "not found"}]
        }
        mock_requests.get.return_value = response

        with self.assertRaises(ApiTennisInvalidResponseError) as ctx:
            module.request_api(method="get_fixtures")
        self.assertIn("404", str(ctx.exception))

    @patch.object(module, "requests")
    def test_fake_apikey_never_appears_in_logs(self, mock_requests):
        response = MagicMock()
        response.status_code = 200
        response.url = (
            f"https://api.example/tennis/?APIkey={FAKE_API_KEY}&method=get_fixtures"
        )
        response.json.return_value = {"result": [{"event_key": "1"}]}
        mock_requests.get.return_value = response

        stream, handler, logger, previous_level = self._capture_logs()
        try:
            module.request_api(method="get_fixtures", params={"date_start": "2026-07-18"})
        finally:
            self._release_logs(handler, logger, previous_level)

        log_output = stream.getvalue()
        self.assertNotIn(FAKE_API_KEY, log_output)
        self.assertIn("APIkey", log_output)
        self.assertIn(REDACTED, log_output)
        mock_requests.get.assert_called_once()
        _, kwargs = mock_requests.get.call_args
        self.assertIn("timeout", kwargs)
        self.assertEqual(kwargs["params"]["APIkey"], FAKE_API_KEY)

    @patch.object(module, "requests")
    def test_does_not_mutate_caller_params(self, mock_requests):
        response = MagicMock()
        response.status_code = 200
        response.url = "https://api.example/tennis/"
        response.json.return_value = {"result": []}
        mock_requests.get.return_value = response

        params = {"date_start": "2026-07-18"}
        module.request_api(method="get_fixtures", params=params)
        self.assertEqual(params, {"date_start": "2026-07-18"})
        self.assertNotIn("APIkey", params)

    @patch.object(module, "requests")
    def test_http_error_does_not_leak_key_in_logs(self, mock_requests):
        response = MagicMock()
        response.status_code = 401
        response.url = f"https://api.example/tennis/?APIkey={FAKE_API_KEY}"
        response.text = f"Unauthorized APIkey={FAKE_API_KEY}"
        mock_requests.get.return_value = response

        stream, handler, logger, previous_level = self._capture_logs()
        try:
            with self.assertRaises(ApiTennisHttpError):
                module.request_api(method="get_fixtures")
        finally:
            self._release_logs(handler, logger, previous_level)

        self.assertNotIn(FAKE_API_KEY, stream.getvalue())

    @patch.object(module, "requests")
    def test_timeout_raises_typed_error(self, mock_requests):
        mock_requests.get.side_effect = requests_exc.Timeout()
        with self.assertRaises(ApiTennisTimeoutError):
            module.request_api(method="get_fixtures")

    @patch.object(module, "requests")
    def test_network_error_raises_typed_error(self, mock_requests):
        mock_requests.get.side_effect = requests_exc.ConnectionError()
        with self.assertRaises(ApiTennisNetworkError):
            module.request_api(method="get_fixtures")

    @patch.object(module, "requests")
    def test_invalid_json_raises_typed_error(self, mock_requests):
        response = MagicMock()
        response.status_code = 200
        response.url = "https://api.example/tennis/"
        response.text = "not-json"
        response.json.side_effect = ValueError("bad json")
        mock_requests.get.return_value = response

        with self.assertRaises(ApiTennisInvalidResponseError):
            module.request_api(method="get_fixtures")


if __name__ == "__main__":
    unittest.main()
