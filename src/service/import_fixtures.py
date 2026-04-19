import logging

from src.entity import Fixture
from src.repository.fixture_repository import FixtureRepository
from src.repository.tournaments_repository import TournamentsRepository
from src.utility.request_api import request_api

tournaments_repo = TournamentsRepository()
fixtures_repo = FixtureRepository()

logging.basicConfig(level=logging.INFO)


def import_all_fixtures(date_start="2000-01-01", date_stop=None, params=None):
    """
    Download e persistenza delle partite di tennis
    :param date_start: Base 2000-01-01
    :param date_stop: Opzionale, se non specificato scarica tutte le partite a partire da date_start
    :param params: parametri di request opzionali, se specificati sovrascrivono date_start e date_stop
    """
    # Recupero tutti i codici dei tornei presenti nel database per evitare di fare richieste API inutili
    tournament_key = set([tournaments.tournament_key for tournaments in tournaments_repo.search_all()])
    # Recupero prima tutti gli event_key univoci delle partite già presenti nel database per evitare di fare richieste API inutili
    search_fixture_key = set([fix.event_key for fix in fixtures_repo.search_all()])
    for key in tournament_key:
        # Mi creo i params
        params = ({"date_start": date_start, "date_stop": date_stop, "tournament_key": key} if date_stop else {
            "date_start": date_start, "tournament_key": key}) if not params else params
        try:
            # Chiamata esterna al servizio API per scaricare le partite del torneo
            response = request_api(method="get_fixtures", params=params)
            if response and len(response) > 0:

                # Filtro le partite scaricate per evitare di inserire partite già presenti nel database e le salvo
                fixtures = [Fixture(**fixture) for fixture in response
                            if fixture.get("event_key") not in search_fixture_key]

                if len(fixtures) > 0:
                    new_fix_update = {fixture.event_key for fixture in fixtures}
                    fixtures_repo.save_all(fixtures)
                    # Aggiungo a search_fixture_key i nuovi event_key per evitare di fare richieste API inutili nei prossimi tornei
                    search_fixture_key.update(new_fix_update)
                    search_fixture_key = set(search_fixture_key)
                    logging.info(f"Imported {len(fixtures)} fixtures for tournament_key: {key}")
            else:
                logging.info(f"No new fixtures to import for tournament_key: {key}")
        except Exception as e:
            logging.error(f"Error in API request: {e}")
            continue
        finally:
            logging.info(f"Finished import for tournament_key: {key}")
            # Reset params
            params = None


import_all_fixtures()
