import type { Player, TennisMatch, Tournament } from "../types/api";

export function formatDate(value: string | null) {
  if (!value) return "-";
  // Bare YYYY-MM-DD is a calendar date: parse at local noon to avoid UTC
  // midnight shifting the displayed day in European timezones.
  const parsed = /^\d{4}-\d{2}-\d{2}$/.test(value)
    ? new Date(`${value}T12:00:00`)
    : new Date(value);
  if (Number.isNaN(parsed.getTime())) return "-";
  return new Intl.DateTimeFormat("it-IT").format(parsed);
}

/** Local calendar date as YYYY-MM-DD (not UTC from toISOString). */
export function todayLocalISODate(now: Date = new Date()) {
  const year = now.getFullYear();
  const month = String(now.getMonth() + 1).padStart(2, "0");
  const day = String(now.getDate()).padStart(2, "0");
  return `${year}-${month}-${day}`;
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
