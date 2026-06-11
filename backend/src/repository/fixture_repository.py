from src.entity import Fixture
from src.repository.base.crud_repository import CrudRepository


class FixtureRepository(CrudRepository):  # Connessione base con i metodi crud

    def __init__(self):
        super().__init__(Fixture)