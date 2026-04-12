from src.entity.event import Event
from src.repository.base.crud_repository import CrudRepository


class EventRepository(CrudRepository):  # Connessione base con i metodi crud

    def __init__(self):
        super().__init__(Event)