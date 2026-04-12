import logging

from sqlalchemy import or_

from src.repository.base.repository_db import SessionLocal

logging.basicConfig(level=logging.DEBUG)


class CrudRepository:
    """
    Classe base per i CRUD delle entità
    """

    def __init__(self, entity):
        super().__init__()
        self.session = SessionLocal()  # Apre la connessione al db
        self.entity = entity  # Nome dell'entità

    def save(self, obj):
        """
        Inserisce un nuovo record se NON esiste
        Aggiorna se esiste gestendo le relazioni
        :return: None
        """
        with self.session as session:
            try:
                # session.add(obj)
                session.merge(obj)
                session.commit()
            except Exception as e:
                logging.error(str(e))
                session.rollback()
                raise

    def save_all(self, list_obj: list):
        """
        Inserisce in maniera massiva le entità
        :return:
        """
        if len(list_obj) > 0:
            with self.session as session:
                try:
                    session.add_all(list_obj)
                    session.commit()
                except Exception as e:
                    logging.error(str(e))
                    session.rollback()
                    raise

    def search_all(self):
        """
        Ritorna tutti i record senza query specifiche
        :return: lista di entità
        """
        with self.session as session:
            try:
                return session.query(self.entity).all()
            except Exception as e:
                logging.error(str(e))
                raise

    def filter_by(self, **kwargs):
        """
        Ricerca puntuale dell'entità
        :param kwargs: query da eseguire
        :return: entità o lista trovata/e
        """
        with self.session as session:
            try:
                return session.query(self.entity).filter_by(**kwargs.get('dict_search'))
            except Exception as e:
                logging.error(str(e))
                raise

    def update(self, **kwargs):
        """
        Aggiorna l'entità
        :param kwargs: query da eseguire
        :return: entità aggiornata
        """
        with self.session as session:
            try:
                field_change = kwargs.get('field_change')
                value_change = kwargs.get('value_change')
                to_dict = kwargs.get('to_dict')
                filter_by = self.filter_by(**kwargs).first()
                if filter_by:
                    setattr(filter_by, field_change, value_change)
                    session.commit()
                return filter_by.to_dict() if to_dict else filter_by
            except Exception as e:
                logging.error(str(e))
                session.rollback()
                raise

    def delete(self, **kwargs):
        """
        Cancella in cascade
        :param kwargs: query da eseguire
        :return: None
        """
        with self.session as session:
            try:
                filter_by = self.filter_by(**kwargs).first()
                if filter_by:
                    session.delete(filter_by)
                    session.commit()
            except Exception as e:
                logging.error(str(e))
                session.rollback()
                raise

    def search_filter(self, filters: dict):
        """
        Ricerca valori passati in filters che creerò delle condizioni da applicare:
        :param filters: dizionario con i filtri da applicare
            - Per ricerche con 'not None' -> {'id': "not None"} (valore in stringa)
            - Per ricerche con 'None' -> {'id': "None"} (valore in stringa)
            - Per ricerche di uguaglianza -> {'name': "pippo"}
            - Per ricerche con OR -> {"OR": [("id_team_home", 135), ("id_team_away", 135)]}
            - Per ricerche con IN -> {'id':[123,145]} -> il valore può essere una lista o tuple
            - Per ricerche con >, <, >=, <=, = -> {'score': '> 10'}
        :return: array di Matches
        """

        conditions = []
        for k, v in filters.items():
            if k == "OR":
                # Costruisco la condizione OR
                or_conditions = []
                for field_name, field_value in v:
                    col = getattr(self.entity, field_name)
                    if isinstance(field_value, (list, tuple)):
                        or_conditions.append(col.in_(field_value))
                    else:
                        or_conditions.append(col == field_value)
                conditions.append(or_(*or_conditions))
            else:
                # Condizione normale AND
                col = getattr(self.entity, k)
                if isinstance(v, (list, tuple)):
                    conditions.append(col.in_(v))
                else:
                    if v == 'not None':
                        conditions.append(col is not None)
                    elif v == 'None':
                        conditions.append(col is None)
                    # TODO: Rivedere questa parte per gestire gli operatori di confronto
                    # elif isinstance(v, str) and '>=' in v:
                    #     v = v.replace('>=', '').strip()
                    #     num_val = float(v) if '.' in v else int(v)
                    #     conditions.append(col >= num_val)
                    # elif isinstance(v, str) and '<=' in v:
                    #     v = v.replace('<=', '').strip()
                    #     num_val = float(v) if '.' in v else int(v)
                    #     conditions.append(col <= num_val)
                    # elif isinstance(v, str) and '>' in v:
                    #     v = v.replace('>', '').strip()
                    #     num_val = float(v) if '.' in v else int(v)
                    #     conditions.append(col > num_val)
                    # elif isinstance(v, str) and '<' in v:
                    #     v = v.replace('<', '').strip()
                    #     num_val = float(v) if '.' in v else int(v)
                    #     conditions.append(col < num_val)
                    # elif isinstance(v, str) and '=' in v:
                    #     v = v.replace('=', '').strip()
                    #     num_val = float(v) if '.' in v else int(v)
                    #     conditions.append(col == num_val)
                    else:
                        conditions.append(col == v)

        with self.session as session:
            try:
                return session.query(self.entity).filter(*conditions).all()
            except Exception as e:
                logging.error(str(e))
                raise

    def massive_update_bulk(self, list_obj: list):
        """
        Update in maniera massiva ma non verrà propagata ai figli
        :param list_obj: lista di chiave:valore = [{pk:1,campo:'valore'}]
        :return: None
        Esempio:
            rows = [{"id": 1, "status": "done"},
                {"id": 2, "status": "pending"}]

            Equivale a:
            UPDATE my_table SET status = 'done' WHERE id = 1;
            UPDATE my_table SET status = 'pending' WHERE id = 2;
        """
        if len(list_obj) > 0:
            with self.session as session:
                try:
                    session.bulk_update_mappings(self.entity, list_obj)
                    session.commit()
                except Exception as e:
                    logging.error(str(e))
                    session.rollback()
                    raise
