import { useEffect, useMemo, useState } from "react";
import { Link, useParams } from "react-router-dom";

import { MetricCard } from "../components/MetricCard";
import { EmptyState, ErrorState, LoadingState } from "../components/Status";
import { apiClient } from "../services/apiClient";
import type { Player, TennisMatch, Tournament } from "../types/api";
import {
  didPlayerWin,
  formatDate,
  formatScore,
  getTournamentSurface,
  matchIncludesPlayer,
  playerDisplayName
} from "../utils/tennis";

const MAX_ROWS = 500;

export function PlayerDetailPage() {
  const { playerId } = useParams();
  const [player, setPlayer] = useState<Player | null>(null);
  const [matches, setMatches] = useState<TennisMatch[]>([]);
  const [tournaments, setTournaments] = useState<Tournament[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    async function loadPlayerDetail() {
      if (!playerId) return;
      try {
        setLoading(true);
        const [playerData, matchesData, tournamentsData] = await Promise.all([
          apiClient.getPlayer(Number(playerId)),
          apiClient.getMatches({ limit: MAX_ROWS }),
          apiClient.getTournaments({ limit: MAX_ROWS })
        ]);
        setPlayer(playerData);
        setMatches(matchesData);
        setTournaments(tournamentsData);
        setError(null);
      } catch (err) {
        setError(err instanceof Error ? err.message : "Errore inatteso.");
      } finally {
        setLoading(false);
      }
    }

    void loadPlayerDetail();
  }, [playerId]);

  const tournamentsByKey = useMemo(() => {
    return new Map(
      tournaments
        .filter((tournament) => tournament.tournament_key !== null)
        .map((tournament) => [tournament.tournament_key as number, tournament])
    );
  }, [tournaments]);

  const playerMatches = useMemo(() => {
    if (!player) return [];
    return matches
      .filter((match) => matchIncludesPlayer(match, player))
      .sort((a, b) => `${b.event_date ?? ""}`.localeCompare(`${a.event_date ?? ""}`));
  }, [matches, player]);

  const wins = player ? playerMatches.filter((match) => didPlayerWin(match, player)).length : 0;
  const losses = Math.max(playerMatches.length - wins, 0);

  const surfaceStats = useMemo(() => {
    if (!player) return [];
    const stats = new Map<string, { wins: number; losses: number }>();
    playerMatches.forEach((match) => {
      const surface = getTournamentSurface(match, tournamentsByKey) ?? "Non disponibile";
      const current = stats.get(surface) ?? { wins: 0, losses: 0 };
      if (didPlayerWin(match, player)) current.wins += 1;
      else current.losses += 1;
      stats.set(surface, current);
    });
    return Array.from(stats.entries());
  }, [player, playerMatches, tournamentsByKey]);

  if (loading) return <LoadingState title="Caricamento dettaglio giocatore..." />;
  if (error) return <ErrorState title="Impossibile caricare il giocatore" message={error} />;
  if (!player) return <EmptyState title="Giocatore non trovato" />;

  return (
    <section className="page">
      <Link className="back-link" to="/players">Torna ai giocatori</Link>
      <header className="page-header">
        <div>
          <h2>{playerDisplayName(player)}</h2>
          <p>{player.player_country ?? "Paese non disponibile"}</p>
        </div>
      </header>

      <div className="metrics-grid">
        <MetricCard label="Partite caricate" value={playerMatches.length} />
        <MetricCard label="Vittorie" value={wins} />
        <MetricCard label="Sconfitte" value={losses} />
        <MetricCard label="Player key" value={player.player_key} />
      </div>

      <article className="panel">
        <h3>Rendimento per superficie</h3>
        {surfaceStats.length === 0 ? (
          <EmptyState title="Dati superficie non disponibili" message="Servono tornei collegati alle partite del giocatore." />
        ) : (
          <div className="surface-list">
            {surfaceStats.map(([surface, stats]) => (
              <span key={surface}>
                {surface}: {stats.wins}W / {stats.losses}L
              </span>
            ))}
          </div>
        )}
      </article>

      <article className="panel">
        <h3>Ultime partite</h3>
        {playerMatches.length === 0 ? (
          <EmptyState title="Nessuna partita collegata" message="Il backend non espone ancora un endpoint dedicato player/matches; filtro dai match caricati." />
        ) : (
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Data</th>
                  <th>Torneo</th>
                  <th>Avversari</th>
                  <th>Vincitore</th>
                  <th>Score</th>
                </tr>
              </thead>
              <tbody>
                {playerMatches.slice(0, 10).map((match) => (
                  <tr key={match.id_fixture}>
                    <td>{formatDate(match.event_date)}</td>
                    <td>{match.tournament_name ?? "-"}</td>
                    <td>{match.event_first_player ?? "-"} vs {match.event_second_player ?? "-"}</td>
                    <td>{match.event_winner ?? "-"}</td>
                    <td>{formatScore(match)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </article>
    </section>
  );
}
