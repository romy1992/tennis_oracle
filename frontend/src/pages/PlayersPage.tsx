import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";

import { EmptyState, ErrorState, LoadingState } from "../components/Status";
import { apiClient } from "../services/apiClient";
import type { Player } from "../types/api";
import { playerDisplayName } from "../utils/tennis";

const MAX_ROWS = 500;

export function PlayersPage() {
  const [players, setPlayers] = useState<Player[]>([]);
  const [query, setQuery] = useState("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    async function loadPlayers() {
      try {
        setLoading(true);
        setPlayers(await apiClient.getPlayers({ limit: MAX_ROWS }));
        setError(null);
      } catch (err) {
        setError(err instanceof Error ? err.message : "Errore inatteso.");
      } finally {
        setLoading(false);
      }
    }

    void loadPlayers();
  }, []);

  const filteredPlayers = useMemo(() => {
    return players.filter((player) =>
      playerDisplayName(player).toLowerCase().includes(query.toLowerCase())
    );
  }, [players, query]);

  if (loading) return <LoadingState title="Caricamento giocatori..." />;
  if (error) return <ErrorState title="Impossibile caricare i giocatori" message={error} />;

  return (
    <section className="page">
      <header className="page-header">
        <div>
          <h2>Giocatori</h2>
          <p>Lista giocatori importati, con ricerca per nome.</p>
        </div>
      </header>

      <div className="filters-grid compact">
        <label>
          Cerca per nome
          <input value={query} onChange={(event) => setQuery(event.target.value)} />
        </label>
      </div>

      {filteredPlayers.length === 0 ? (
        <EmptyState title="Nessun giocatore trovato" message="Importa i giocatori o modifica la ricerca." />
      ) : (
        <div className="cards-grid">
          {filteredPlayers.map((player) => (
            <Link className="player-card" key={player.id_player} to={`/players/${player.id_player}`}>
              <strong>{playerDisplayName(player)}</strong>
              <span>{player.player_country ?? "Paese non disponibile"}</span>
              <small>Key: {player.player_key}</small>
            </Link>
          ))}
        </div>
      )}
    </section>
  );
}
