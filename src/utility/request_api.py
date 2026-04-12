import logging
import os

import requests
from dotenv import load_dotenv

logging.basicConfig(level=logging.DEBUG)
load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), '../../properties/config.env'))
API_KEY = os.getenv("API_TENNIS_KEY")
BASE_URL = os.getenv("API_TENNIS_BASE")


def request_api(method: str, params: dict = None):
    if not params:
        params = {}
    params.update({'APIkey': API_KEY, "method": method if method else ""})
    response = requests.get(BASE_URL, params=params)
    if response.status_code == 200:
        response_json = response.json()["result"]
        if isinstance(response_json, list) and response_json[0].get("cod"):
            logging.error(f"Error in API request: {response_json}")
            response.raise_for_status()
            return None
        return response_json
    else:
        logging.error(f"Error in API request: {response.status_code} - {response.text}")
        response.raise_for_status()
        return None
