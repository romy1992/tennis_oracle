import logging

from backend.src.entity import Event, Tournament
from backend.src.repository.event_repository import EventRepository
from backend.src.repository.tournaments_repository import TournamentsRepository
from backend.src.utility.request_api import request_api

logging.basicConfig(level=logging.INFO)


class BasicImportService:

    @classmethod
    def import_event(cls):
        """
        Import lista di eventi una TANTUM
        :return:
        """
        response = request_api(method="get_events")
        events_repo = EventRepository()
        events = [Event(**event) for event in response]
        events_repo.save_all(events)

    @classmethod
    def import_tournaments(cls):
        """
        Import lista di tornai una TANTUM
        """
        response = request_api(method="get_tournaments")
        tournaments_repo = TournamentsRepository()
        tournaments = [Tournament(**tournament) for tournament in response]
        tournaments_repo.save_all(tournaments)


def basic():
    basic_import = BasicImportService()
    basic_import.import_event()
    basic_import.import_tournaments()
