import logging

from backend.src.entity import Player, Standing
from backend.src.repository.player_repository import PlayerRepository
from backend.src.repository.standing_repository import StandingRepository
from backend.src.utility.request_api import request_api

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
            search_all_standings = standings_repo.search_all()
            # player_key non e' globalmente univoco: va usato insieme a league.
            standing_id_by_player_key_league = {
                (str(ss.player_key), ss.league): ss.id_standing for ss in search_all_standings
            }

            list_standings_update = [
                {
                    "id_standing": standing_id_by_player_key_league[(str(s.player_key), s.league)],
                    "place": s.place,
                    "movement": s.movement,
                    "points": s.points,
                }
                for s in standings
                if (str(s.player_key), s.league) in standing_id_by_player_key_league
            ]

            list_standings_insert = [
                s
                for s in standings
                if (str(s.player_key), s.league) not in standing_id_by_player_key_league
            ]

            standings_repo.massive_update_bulk(list_standings_update)
            standings_repo.save_all(list_standings_insert)
            logging.info(
                "Standings update completato: update=%s insert=%s",
                len(list_standings_update),
                len(list_standings_insert),
            )
    else:
        logging.error(f"Error in API request: {response}")


def refresh_standing_players():
    """
    Esegue il download/refresh della classifica dei tennisti ATP (maschile) e WTA (femminile) e salva i dati nel database.
    """
    import_standings(params={"event_type": "ATP"}, type_operation="update")
    import_standings(params={"event_type": "WTA"}, type_operation="update")


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
