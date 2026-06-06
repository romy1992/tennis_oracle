import logging
import os
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import requests
from dotenv import load_dotenv

logging.basicConfig(level=logging.INFO)
logging.getLogger("urllib3").setLevel(logging.WARNING)
logging.getLogger("urllib3.connectionpool").setLevel(logging.WARNING)
load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), '../../properties/config.env'))
API_KEY = os.getenv("API_TENNIS_KEY")
BASE_URL = os.getenv("API_TENNIS_BASE")


class ApiTennisError(RuntimeError):
    pass


def _sanitize_url(url):
    parts = urlsplit(url)
    sanitized_query = [
        (key, "****" if key == "APIkey" else value)
        for key, value in parse_qsl(parts.query, keep_blank_values=True)
    ]
    query = urlencode(sanitized_query)
    return urlunsplit((parts.scheme, parts.netloc, parts.path, query, parts.fragment))


def _is_api_error(response_json):
    if isinstance(response_json, list) and response_json:
        return isinstance(response_json[0], dict) and response_json[0].get("cod")
    if isinstance(response_json, dict):
        return response_json.get("cod")
    return False


def request_api(method: str, params: dict = None):
    request_params = dict(params) if params else {}
    request_params.update({'APIkey': API_KEY, "method": method if method else ""})
    response = requests.get(BASE_URL, params=request_params)
    if response.status_code == 200:
        logging.info(f"Call URL: {_sanitize_url(response.url)}")
        response_json = response.json().get("result")
        if _is_api_error(response_json):
            logging.error(f"Error in API request: {response_json}")
            raise ApiTennisError(str(response_json))
        return response_json
    else:
        logging.error(f"Error in API request: {response.status_code} - {response.text}")
        response.raise_for_status()
        return None
