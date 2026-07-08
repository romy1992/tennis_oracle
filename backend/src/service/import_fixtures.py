import logging
import json
from datetime import datetime, timedelta
from pathlib import Path

from backend.src.entity import Fixture
from backend.src.repository.fixture_repository import FixtureRepository
from backend.src.repository.tournaments_repository import TournamentsRepository
from backend.src.service.import_stading_player import refresh_standing_players
from backend.src.utility.request_api import request_api

tournaments_repo = TournamentsRepository()
fixtures_repo = FixtureRepository()

logging.basicConfig(level=logging.INFO)


#region agent log
def _agent_debug_log(hypothesis_id: str, location: str, message: str, data: dict) -> None:
    payload = {
        "sessionId": "8c43c3",
        "runId": "pre-fix",
        "hypothesisId": hypothesis_id,
        "location": location,
        "message": message,
        "data": data,
        "timestamp": int(datetime.now().timestamp() * 1000),
    }
    try:
        Path(r"c:\Users\trott\git\tennis_oracle\debug-8c43c3.log").open("a", encoding="utf-8").write(json.dumps(payload, default=str) + "\n")
    except Exception:
        pass
#endregion


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
    try:
        # Chiamata esterna al servizio API per scaricare le partite del torneo
        response = request_api(method="get_fixtures", params=params)
        if response and len(response) > 0:
            event_keys = [fixture.get("event_key") for fixture in response if fixture.get("event_key") is not None]
            existing_rows = fixtures_repo.search_filter({"event_key": event_keys}) if event_keys else []
            existing_by_key = {fixture.event_key: fixture for fixture in existing_rows}
            search_fixture_key = set(existing_by_key)
            existing_payloads = [
                fixture for fixture in response if fixture.get("event_key") in search_fixture_key
            ]
            #region agent log
            _agent_debug_log(
                "H6",
                "backend/src/service/import_fixtures.py:import_fixtures_by_params",
                "Fetched played fixtures and compared them with existing rows",
                {
                    "params": params,
                    "response_count": len(response),
                    "existing_count": len(existing_payloads),
                    "existing_with_winner_count": sum(1 for fixture in existing_payloads if fixture.get("event_winner")),
                    "new_count": sum(1 for fixture in response if fixture.get("event_key") not in search_fixture_key),
                    "existing_winner_sample": [
                        {
                            "event_key": fixture.get("event_key"),
                            "event_winner": fixture.get("event_winner"),
                            "event_status": fixture.get("event_status"),
                        }
                        for fixture in existing_payloads
                        if fixture.get("event_winner")
                    ][:10],
                },
            )
            #endregion
            # Filtro le partite scaricate per evitare di inserire partite già presenti nel database e le salvo
            fixtures = [Fixture(**fixture) for fixture in response
                        if fixture.get("event_key") not in search_fixture_key]
            fixture_updates = []
            for fixture in existing_payloads:
                existing = existing_by_key.get(fixture.get("event_key"))
                if existing is None:
                    continue
                update = {
                    key: value
                    for key, value in fixture.items()
                    if key in Fixture.__table__.columns and key != "id_fixture"
                }
                update["id_fixture"] = existing.id_fixture
                fixture_updates.append(update)

            if fixture_updates:
                fixtures_repo.massive_update_bulk(fixture_updates)
                logging.info(f"Updated {len(fixture_updates)} existing fixtures")

            if len(fixtures) > 0:
                for fixture in fixtures:
                    # Recupero gli event_key per poter chiamare l'api delle odds e agganciarle prima di salvarle
                    event_key_fixture = fixture.event_key
                    # chiamo api odds
                    odds = request_api(method="get_odds", params={"match_key": event_key_fixture})
                    if odds and len(odds) > 0:
                        fixture.odds = odds

                fixtures_repo.save_all(fixtures)
                logging.info(f"Imported {len(fixtures)} fixtures")
        else:
            logging.info(f"No new fixtures to import for params: {params}")
    except Exception as e:
        logging.error(f"Error in API request: {e} with params: {params}")
        raise


def calculate_date(days_back_start: int = 1, days_back_stop: int = 0):
    """
    Calcola intervallo date per import giornaliero.
    days_back_start=1, days_back_stop=0 -> da ieri a oggi (default cron).
    """
    format_data = "%Y-%m-%d"
    current_data = datetime.now()
    date_start = (current_data - timedelta(days=days_back_start)).strftime(format_data)
    date_stop = (current_data - timedelta(days=days_back_stop)).strftime(format_data)
    return date_start, date_stop


def run_daily_fixture_import(days_back_start: int = 1, days_back_stop: int = 0):
    """Import partite nel DB configurato in repository_db (di solito il locale)."""
    date_start, date_stop = calculate_date(days_back_start, days_back_stop)
    params = {"date_start": date_start, "date_stop": date_stop}

    logging.info("Avvio import fixtures: %s", params)
    import_fixtures_by_params(params)
    logging.info("Import fixtures completato.")

    logging.info("Aggiornamento della classifica maschile e femminile")
    refresh_standing_players()


if __name__ == "__main__":
    run_daily_fixture_import(days_back_start=2, days_back_stop=0)  # Esempio: import partite da 3 giorni fa a oggi
