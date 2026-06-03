import logging

from src.entity import Player, Standing
from src.repository.player_repository import PlayerRepository
from src.repository.standing_repository import StandingRepository
from src.utility.request_api import request_api

logging.basicConfig(level=logging.INFO)

standings_repo = StandingRepository()
player_repo = PlayerRepository()


def import_standings(params=None, type_operation="insert"):
    """
      Import della classifica dei tennisti ATP (maschile) e WTA (femminile).Da eseguire una volta al mese
      :param type_operation:
      :param params: esempio event_type per specificare se scaricare la classifica ATP o WTA, se non specificato scarica la classifica ATP
    """
    response = request_api(method="get_standings", params=params)
    if response:

        standings = [Standing(**standing) for standing in response]
        if type_operation == "insert":
            standings_repo.save_all(standings)
        elif type_operation == "update":
            standings_repo.update(standings)  # TODO da sistemare con update
    else:
        logging.error(f"Error in API request: {response}")


def refresh_standing_players():
    """
    Esegue il download/refresh della classifica dei tennisti ATP (maschile) e WTA (femminile) e salva i dati nel database.
    """
    import_standings(params={"event_type": "ATP"})
    import_standings(params={"event_type": "WTA"})


def import_players():
    """
    Esegue il download dei tennisti con più info su di loro e sulle partite effettuate
    """
    players = []
    # Recupero gli id dei tennisti
    ids_players = set(standings_repo.search_column_values("player_key"))
    try:
        for id_player in ids_players:
            # Recupero
            response = request_api(method="get_players", params={"player_key": id_player})
            if response and len(response) > 0:
                # Aggiungo alla lista
                players.append(response[0])
            else:
                logging.error(f"Error in API request: {response}")
    except Exception as e:
        logging.error(f"Error in API request: {e}")
    finally:
        # Inserisco DOPO aver fatto le chiamate
        if len(players) > 0:
            player_repo.save_all([Player(**player) for player in players])
