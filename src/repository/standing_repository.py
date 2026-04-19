from src.entity import Standing
from src.repository.base.crud_repository import CrudRepository


class StandingRepository(CrudRepository):  # Connessione base con i metodi crud

    def __init__(self):
        super().__init__(Standing)
