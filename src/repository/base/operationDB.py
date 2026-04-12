"""
@staticmethod : rende il metodo statico
@classmethod : rende il metodo di classe (riceve la classe(cls) come primo argomento)
nessun annotation : metodo normale (riceve l'istanza(self) come primo argomento)
self e cls stessa cosa, ma self è per i metodi di istanza e cls è per i metodi di classe. I metodi statici non ricevono né self né cls come argomento, poiché non sono legati a nessuna istanza o classe specifica.

"""
import src.entity
from src.entity.base import Base
from src.repository.base.repository_db import engine

_ = src.entity


class OperationDB:

    @staticmethod
    def reset_db():
        """
        Attenzione: cancella TUTTI i dati
        In caso di necessità, droppa tutto il db cancellandolo
        """
        Base.metadata.drop_all(bind=engine)
        Base.metadata.create_all(bind=engine)
        print("Database ricreato da zero.")

    @staticmethod
    def refresh_db():
        """
            Ricrea le tabelle senza cancellare i dati
            Utile per aggiornare la struttura del db senza perdere i dati
        """
        Base.metadata.create_all(bind=engine)
        print("Database aggiornato.")
