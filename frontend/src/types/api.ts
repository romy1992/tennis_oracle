export type BackendHealth = {
  status: string;
  environment: string;
  debug: boolean;
};

export type TennisMatch = {
  id_fixture: number;
  event_key: number;
  event_date: string | null;
  event_time: string | null;
  event_first_player: string | null;
  first_player_key: number | null;
  event_second_player: string | null;
  second_player_key: number | null;
  event_final_result: string | null;
  event_game_result: string | null;
  event_serve: string | null;
  event_winner: string | null;
  event_status: string | null;
  event_type_type: string | null;
  tournament_name: string | null;
  tournament_key: number | null;
  tournament_round: string | null;
  tournament_season: string | null;
  event_live: string | null;
  event_first_player_logo: string | null;
  event_second_player_logo: string | null;
  event_qualification: string | null;
  pointbypoint: unknown | null;
  scores: unknown | null;
  statistics: unknown | null;
  odds: unknown | null;
};

export type Player = {
  id_player: number;
  player_key: number;
  player_name: string | null;
  player_full_name: string | null;
  player_country: string | null;
  player_bday: string | null;
  player_logo: string | null;
  stats: unknown | null;
  tournaments: unknown | null;
};

export type Tournament = {
  id_tournament: number;
  tournament_key: number | null;
  tournament_name: string | null;
  event_type_key: number | null;
  event_type_type: string | null;
  tournament_sourface: string | null;
};

export type ListParams = {
  limit?: number;
  offset?: number;
};
