from src.entity import Event, Tournament
from src.repository.base.operationDB import OperationDB
from src.repository.event_repository import EventRepository
from src.repository.tournaments_repository import TournamentsRepository
from src.utility.request_api import request_api


class BasicImportService:
    def __init__(self):
        # params = {"date_start": "2022-01-01", "date_stop": "2022-12-31"}
        pass

    @classmethod
    def import_event(cls):
        response = request_api(method="get_events")
        events_repo = EventRepository()
        events = [Event(**event) for event in response]
        events_repo.save_all(events)

    @classmethod
    def import_tournaments(cls):
        response = request_api(method="get_tournaments")
        tournaments_repo = TournamentsRepository()
        tournaments = [Tournament(**tournament) for tournament in response]
        tournaments_repo.save_all(tournaments)


basic_import = BasicImportService()
basic_import.import_event()
basic_import.import_tournaments()
