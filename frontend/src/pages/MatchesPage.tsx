import { useEffect, useMemo, useState } from "react";

import { EmptyState, ErrorState, LoadingState } from "../components/Status";
import { apiClient } from "../services/apiClient";
import type { TennisMatch, Tournament } from "../types/api";
import { formatDate, formatScore, getTournamentSurface } from "../utils/tennis";

const MAX_ROWS = 500;

export function MatchesPage() {
  const [matches, setMatches] = useState<TennisMatch[]>([]);
  const [tournaments, setTournaments] = useState<Tournament[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [filters, setFilters] = useState({
    tournament: "",
    surface: "",
    year: "",
    player: ""
  });

  useEffect(() => {
    async function loadMatches() {
      try {
        setLoading(true);
        const [matchesData, tournamentsData] = await Promise.all([
          apiClient.getMatches({ limit: MAX_ROWS }),
          apiClient.getTournaments({ limit: MAX_ROWS })
        ]);
        setMatches(matchesData);
        setTournaments(tournamentsData);
        setError(null);
      } catch (err) {
        setError(err instanceof Error ? err.message : "Errore inatteso.");
      } finally {
        setLoading(false);
      }
    }

    void loadMatches();
  }, []);

  const tournamentsByKey = useMemo(() => {
    return new Map(
      tournaments
        .filter((tournament) => tournament.tournament_key !== null)
        .map((tournament) => [tournament.tournament_key as number, tournament])
    );
  }, [tournaments]);

  const filteredMatches = useMemo(() => {
    return matches.filter((match) => {
      const surface = getTournamentSurface(match, tournamentsByKey) ?? "";
      const year = match.event_date ? new Date(match.event_date).getFullYear().toString() : "";
      const players = `${match.event_first_player ?? ""} ${match.event_second_player ?? ""}`.toLowerCase();

      return (
        (filters.tournament === "" ||
          (match.tournament_name ?? "").toLowerCase().includes(filters.tournament.toLowerCase())) &&
        (filters.surface === "" || surface.toLowerCase().includes(filters.surface.toLowerCase())) &&
        (filters.year === "" || year === filters.year) &&
        (filters.player === "" || players.includes(filters.player.toLowerCase()))
      );
    });
  }, [filters, matches, tournamentsByKey]);

  if (loading) return <LoadingState title="Caricamento partite..." />;
  if (error) return <ErrorState title="Impossibile caricare le partite" message={error} />;

  return (
    <section className="page">
      <header className="page-header">
        <div>
          <h2>Partite</h2>
          <p>Tabella delle partite importate dal database.</p>
        </div>
      </header>

      <div className="filters-grid">
        <label>
          Torneo
          <input value={filters.tournament} onChange={(event) => setFilters({ ...filters, tournament: event.target.value })} />
        </label>
        <label>
          Superficie
          <input value={filters.surface} onChange={(event) => setFilters({ ...filters, surface: event.target.value })} />
        </label>
        <label>
          Anno
          <input value={filters.year} onChange={(event) => setFilters({ ...filters, year: event.target.value })} />
        </label>
        <label>
          Player
          <input value={filters.player} onChange={(event) => setFilters({ ...filters, player: event.target.value })} />
        </label>
      </div>

      {filteredMatches.length === 0 ? (
        <EmptyState title="Nessuna partita trovata" message="Modifica i filtri o verifica che la tabella fixture contenga dati." />
      ) : (
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Data</th>
                <th>Torneo</th>
                <th>Superficie</th>
                <th>Player 1</th>
                <th>Player 2</th>
                <th>Vincitore</th>
                <th>Round</th>
                <th>Score</th>
              </tr>
            </thead>
            <tbody>
              {filteredMatches.map((match) => (
                <tr key={match.id_fixture}>
                  <td>{formatDate(match.event_date)}</td>
                  <td>{match.tournament_name ?? "-"}</td>
                  <td>{getTournamentSurface(match, tournamentsByKey) ?? "Non disponibile"}</td>
                  <td>{match.event_first_player ?? "-"}</td>
                  <td>{match.event_second_player ?? "-"}</td>
                  <td>{match.event_winner ?? "-"}</td>
                  <td>{match.tournament_round ?? "-"}</td>
                  <td>{formatScore(match)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}
