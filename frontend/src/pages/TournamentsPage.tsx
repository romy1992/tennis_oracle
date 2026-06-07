import { useEffect, useMemo, useState } from "react";

import { EmptyState, ErrorState, LoadingState } from "../components/Status";
import { apiClient } from "../services/apiClient";
import type { TennisMatch, Tournament } from "../types/api";

const MAX_ROWS = 500;

export function TournamentsPage() {
  const [tournaments, setTournaments] = useState<Tournament[]>([]);
  const [matches, setMatches] = useState<TennisMatch[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    async function loadTournaments() {
      try {
        setLoading(true);
        const [tournamentsData, matchesData] = await Promise.all([
          apiClient.getTournaments({ limit: MAX_ROWS }),
          apiClient.getMatches({ limit: MAX_ROWS })
        ]);
        setTournaments(tournamentsData);
        setMatches(matchesData);
        setError(null);
      } catch (err) {
        setError(err instanceof Error ? err.message : "Errore inatteso.");
      } finally {
        setLoading(false);
      }
    }

    void loadTournaments();
  }, []);

  const matchesByTournament = useMemo(() => {
    const counts = new Map<number, number>();
    matches.forEach((match) => {
      if (match.tournament_key !== null) {
        counts.set(match.tournament_key, (counts.get(match.tournament_key) ?? 0) + 1);
      }
    });
    return counts;
  }, [matches]);

  if (loading) return <LoadingState title="Caricamento tornei..." />;
  if (error) return <ErrorState title="Impossibile caricare i tornei" message={error} />;

  return (
    <section className="page">
      <header className="page-header">
        <div>
          <h2>Tornei</h2>
          <p>Lista tornei e numero partite presenti nel DB caricato.</p>
        </div>
      </header>

      {tournaments.length === 0 ? (
        <EmptyState title="Nessun torneo trovato" message="Esegui il bootstrap tornei o verifica la tabella tournament." />
      ) : (
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Torneo</th>
                <th>Superficie</th>
                <th>Nazione/Città</th>
                <th>Tipo evento</th>
                <th>Partite DB</th>
              </tr>
            </thead>
            <tbody>
              {tournaments.map((tournament) => (
                <tr key={tournament.id_tournament}>
                  <td>{tournament.tournament_name ?? "-"}</td>
                  <td>{tournament.tournament_sourface ?? "Non disponibile"}</td>
                  <td>Non esposto dal backend</td>
                  <td>{tournament.event_type_type ?? "-"}</td>
                  <td>
                    {tournament.tournament_key !== null
                      ? matchesByTournament.get(tournament.tournament_key) ?? 0
                      : 0}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}
