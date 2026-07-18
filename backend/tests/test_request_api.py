import unittest
from unittest.mock import MagicMock, patch

from backend.src.utility import request_api as module


class RequestApiTest(unittest.TestCase):
    @patch.object(module, "requests")
    def test_raises_on_string_result(self, mock_requests):
        response = MagicMock()
        response.status_code = 200
        response.url = "https://example.test"
        response.json.return_value = {
            "result": "Maximum date range for odds is 7 days."
        }
        mock_requests.get.return_value = response

        with self.assertRaises(RuntimeError) as ctx:
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

        with self.assertRaises(RuntimeError) as ctx:
            module.request_api(method="get_fixtures")
        self.assertIn("404", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
