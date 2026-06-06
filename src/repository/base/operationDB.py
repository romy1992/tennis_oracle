"""
@staticmethod : rende il metodo statico
@classmethod : rende il metodo di classe (riceve la classe(cls) come primo argomento)
nessun annotation : metodo normale (riceve l'istanza(self) come primo argomento)
self e cls stessa cosa, ma self è per i metodi di istanza e cls è per i metodi di classe. I metodi statici non ricevono né self né cls come argomento, poiché non sono legati a nessuna istanza o classe specifica.

"""
import os

import src.entity
from alembic import command
from alembic.config import Config

from src.entity.base import Base
from src.repository.base.repository_db import engine

_ = src.entity

ALEMBIC_INI = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "../../../alembic.ini")
)


class OperationDB:

    @staticmethod
    def _alembic_config():
        return Config(ALEMBIC_INI)

    @staticmethod
    def reset_db():
        """
        Attenzione: cancella TUTTI i dati
        In caso di necessità, droppa tutto il db cancellandolo
        """
        Base.metadata.drop_all(bind=engine)
        command.upgrade(OperationDB._alembic_config(), "head")
        print("Database ricreato da zero tramite Alembic.")

    @staticmethod
    def refresh_db():
        """
            Applica le migrazioni Alembic senza cancellare i dati
        """
        command.upgrade(OperationDB._alembic_config(), "head")
        print("Database aggiornato tramite Alembic.")

operationDB = OperationDB()