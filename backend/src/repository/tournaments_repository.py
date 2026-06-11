from src.entity.tournaments import Tournament
from src.repository.base.crud_repository import CrudRepository


class TournamentsRepository(CrudRepository):  # Connessione base con i metodi crud

    def __init__(self):
        super().__init__(Tournament)