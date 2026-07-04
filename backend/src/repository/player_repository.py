from backend.src.entity import Player
from backend.src.repository.base.crud_repository import CrudRepository


class PlayerRepository(CrudRepository):  # Connessione base con i metodi crud

    def __init__(self):
        super().__init__(Player)
