import logging
from datetime import datetime, timedelta

from src.entity import Fixture
from src.repository.fixture_repository import FixtureRepository
from src.repository.tournaments_repository import TournamentsRepository
from src.utility.request_api import request_api

tournaments_repo = TournamentsRepository()
fixtures_repo = FixtureRepository()

logging.basicConfig(level=logging.INFO)


def _new_import_stats(params):
    return {
        "params": dict(params) if params else {},
        "status": "success",
        "fixtures_received": 0,
        "fixtures_already_present": 0,
        "fixtures_imported": 0,
        "odds_enriched": 0,
        "errors": [],
    }


def import_all_fixtures(date_start="2000-01-01", date_stop=None, params=None):
    """
    Download e persistenza delle partite di tennis
    :param date_start: Base 2000-01-01
    :param date_stop: Opzionale, se non specificato scarica tutte le partite a partire da date_start
    :param params: parametri di request opzionali, se specificati sovrascrivono date_start e date_stop
    """
    # Recupero tutti i codici dei tornei presenti nel database per evitare di fare richieste API inutili
    tournament_key = set(tournaments_repo.search_column_values("tournament_key"))
    # Recupero prima tutti gli event_key univoci delle partite già presenti nel database per evitare di fare richieste API inutili
    search_fixture_key = set(fixtures_repo.search_column_values("event_key"))
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
        finally:
            logging.info(f"Finished import for tournament_key: {key}")
            # Reset params
            params = None


def import_odds_full_by_tournament(params=None, tournament_key=None):
    """
    Metodo per importare le quote di tutti i match di un torneo
    :param tournament_key: se tournament_key è vuoto scarica tutte le quote dei tornei presenti nel database, altrimenti scarica solo le quote dei tornei specificati
    :param params: se params è vuoto scarica tutte le quote dei tornei presenti nel database
    :return: None
    """
    if not params:
        params = {"date_start": "1990-01-01", "date_stop": "2026-12-31"}
    if not tournament_key:
        # Recupero tutti i codici dei tornei presenti nel database per evitare di fare richieste API inutili
        tournament_key = set(tournaments_repo.search_column_values("tournament_key"))

    for ind, key in enumerate(tournament_key):
        list_odds = []
        logging.info(f"Starting import for tournament_key: {key} -> {ind + 1}/{len(tournament_key)}")
        params.update({"tournament_key": key})
        try:
            # Chiamo servizio di odds
            response = request_api(method="get_odds", params=params)
            if response and len(response) > 0:
                logging.info(f"Imported {len(response)} odds")
                for odd in response.items():
                    # Per ogni odds mi recupero l'id del match e le sue quote
                    key_match = odd[0]
                    dict_odd = odd[1]

                    # Cerco il match e se presente lo aggiungo alla lista solo se esiste e NON ha già delle odds salvate
                    match_tennis = fixtures_repo.search_filter({"event_key": key_match})
                    if match_tennis and len(match_tennis) > 0 and not match_tennis[0].odds:
                        id_fixture = match_tennis[0].id_fixture
                        list_odds.append({"id_fixture": id_fixture, "odds": dict_odd})
            else:
                logging.info("No new odds to import with tournament_key: {key}")
        except Exception as e:
            logging.error(f"Error in API request: {e} for tournament_key: {key}")
        finally:
            logging.info(f"Finished import for tournament_key: {key} -> {ind + 1}/{len(tournament_key)}")
            # Se la lista contiene elementi, faccio un update del match aggiungendo le quote
            if len(list_odds) > 0:
                fixtures_repo.massive_update_bulk(list_odds)


def import_fixtures_by_params(params):
    stats = _new_import_stats(params)
    try:
        # Recupero prima tutti gli event_key univoci delle partite già presenti nel database per evitare di fare richieste API inutili
        search_fixture_key = set(fixtures_repo.search_column_values("event_key"))
        # Chiamata esterna al servizio API per scaricare le partite del torneo
        response = request_api(method="get_fixtures", params=dict(params))
        if response and len(response) > 0:
            stats["fixtures_received"] = len(response)
            # Filtro le partite scaricate per evitare di inserire partite già presenti nel database e le salvo
            fixtures_to_import = [
                fixture for fixture in response
                if fixture.get("event_key") not in search_fixture_key
            ]
            stats["fixtures_already_present"] = len(response) - len(fixtures_to_import)
            fixtures = [Fixture(**fixture) for fixture in fixtures_to_import]

            if len(fixtures) > 0:
                for fixture in fixtures:
                    # Recupero gli event_key per poter chiamare l'api delle odds e agganciarle prima di salvarle
                    event_key_fixture = fixture.event_key
                    try:
                        # chiamo api odds
                        odds = request_api(method="get_odds", params={"match_key": event_key_fixture})
                        if odds and len(odds) > 0:
                            fixture.odds = odds
                            stats["odds_enriched"] += 1
                    except Exception as e:
                        message = f"Error importing odds for event_key {event_key_fixture}: {e}"
                        stats["errors"].append(message)
                        logging.error(message)

                fixtures_repo.save_all(fixtures)
                stats["fixtures_imported"] = len(fixtures)
                logging.info(f"Imported {len(fixtures)} fixtures")
        else:
            logging.info(f"No new fixtures to import for params: {params}")
    except Exception as e:
        stats["status"] = "failed"
        stats["errors"].append(str(e))
        logging.error(f"Error in API request: {e} with params: {params}")
    if stats["errors"] and stats["status"] == "success":
        stats["status"] = "completed_with_errors"
    return stats


def calculate_date():
    """
    0: Oggi
    -1: Ieri
    -2: Altro ieri
    +1: Domani
    +2: DopoDomani
    :return:
    """
    # Formato richiesto è esempio:"2025-02-12"
    format_data = '%Y-%m-%d'
    current_data = datetime.now()
    # Scegliere da che giorno indietro si vuole andare per recuperare le partite
    date_start = (current_data - timedelta(days=1)).strftime(format_data)
    # Fino a ...
    date_stop = (current_data - timedelta(days=0)).strftime(format_data)
    return date_start, date_stop


def run_default_import():
    date_start, date_stop = calculate_date()
    params = {"date_start": date_start, "date_stop": date_stop}
    return import_fixtures_by_params(params)


if __name__ == "__main__":
    run_default_import()
    # import_odds_full_by_tournament(params=params)
