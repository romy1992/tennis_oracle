from src.entity import Player
from src.repository.base.crud_repository import CrudRepository


class PlayerRepository(CrudRepository):  # Connessione base con i metodi crud

    def __init__(self):
        super().__init__(Player)
