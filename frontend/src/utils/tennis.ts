import type { Player, TennisMatch, Tournament } from "../types/api";

export function formatDate(value: string | null) {
  if (!value) return "-";
  return new Intl.DateTimeFormat("it-IT").format(new Date(value));
}

export function formatScore(match: TennisMatch) {
  if (match.event_final_result) return match.event_final_result;
  if (match.event_game_result) return match.event_game_result;
  if (!match.scores) return "-";
  if (typeof match.scores === "string") return match.scores;
  return JSON.stringify(match.scores);
}

export function getTournamentSurface(
  match: TennisMatch,
  tournamentsByKey: Map<number, Tournament>
) {
  if (match.tournament_key === null) return null;
  return tournamentsByKey.get(match.tournament_key)?.tournament_sourface ?? null;
}

export function playerDisplayName(player: Player) {
  return player.player_full_name || player.player_name || `Player ${player.player_key}`;
}

export function matchIncludesPlayer(match: TennisMatch, player: Player) {
  const name = playerDisplayName(player).toLowerCase();
  return (
    match.first_player_key === player.player_key ||
    match.second_player_key === player.player_key ||
    (match.event_first_player ?? "").toLowerCase().includes(name) ||
    (match.event_second_player ?? "").toLowerCase().includes(name)
  );
}

export function didPlayerWin(match: TennisMatch, player: Player) {
  const winner = (match.event_winner ?? "").toLowerCase();
  const names = [player.player_name, player.player_full_name]
    .filter(Boolean)
    .map((value) => String(value).toLowerCase());
  return names.some((name) => winner.includes(name));
}
