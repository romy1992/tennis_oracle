import unittest
from unittest.mock import patch

from backend.src.utility.request_api import request_api


class _Response:
    status_code = 200
    url = "https://example.test/tennis/?method=get_fixtures"
    text = ""

    def json(self):
        return {"result": []}

    def raise_for_status(self):
        raise AssertionError("raise_for_status should not be called")


class RequestApiTest(unittest.TestCase):
    @patch("src.utility.request_api.requests.get", return_value=_Response())
    def test_empty_result_list_is_returned(self, _mock_get):
        self.assertEqual(request_api("get_fixtures"), [])


if __name__ == "__main__":
    unittest.main()
