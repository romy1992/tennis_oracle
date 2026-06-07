import { useEffect, useMemo, useState } from "react";

import { MetricCard } from "../components/MetricCard";
import { EmptyState, ErrorState, LoadingState } from "../components/Status";
import { apiClient } from "../services/apiClient";
import type { BackendHealth, Player, TennisMatch, Tournament } from "../types/api";
import { formatDate, formatScore } from "../utils/tennis";

type DashboardData = {
  health: BackendHealth | null;
  matches: TennisMatch[];
  players: Player[];
  tournaments: Tournament[];
};

const MAX_ROWS = 500;

export function Dashboard() {
  const [data, setData] = useState<DashboardData | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    async function loadDashboard() {
      try {
        setLoading(true);
        const [health, matches, players, tournaments] = await Promise.all([
          apiClient.getHealth(),
          apiClient.getMatches({ limit: MAX_ROWS }),
          apiClient.getPlayers({ limit: MAX_ROWS }),
          apiClient.getTournaments({ limit: MAX_ROWS })
        ]);
        setData({ health, matches, players, tournaments });
        setError(null);
      } catch (err) {
        setError(err instanceof Error ? err.message : "Errore inatteso.");
      } finally {
        setLoading(false);
      }
    }

    void loadDashboard();
  }, []);

  const latestMatch = useMemo(() => {
    if (!data?.matches.length) return null;
    return [...data.matches].sort((a, b) => {
      const left = `${a.event_date ?? ""} ${a.event_time ?? ""}`;
      const right = `${b.event_date ?? ""} ${b.event_time ?? ""}`;
      return right.localeCompare(left);
    })[0];
  }, [data]);

  if (loading) return <LoadingState title="Caricamento dashboard..." />;
  if (error) return <ErrorState title="Backend non raggiungibile" message={error} />;
  if (!data) return <EmptyState title="Nessun dato disponibile" />;

  return (
    <section className="page">
      <header className="page-header">
        <div>
          <h2>Dashboard</h2>
          <p>Panoramica dei dati disponibili dagli endpoint FastAPI.</p>
        </div>
        <span className={`pill ${data.health?.status === "ok" ? "pill-ok" : ""}`}>
          Backend: {data.health?.status ?? "non disponibile"}
        </span>
      </header>

      <div className="metrics-grid">
        <MetricCard label="Partite importate" value={data.matches.length} hint={`max ${MAX_ROWS}`} />
        <MetricCard label="Giocatori" value={data.players.length} hint={`max ${MAX_ROWS}`} />
        <MetricCard label="Tornei" value={data.tournaments.length} hint={`max ${MAX_ROWS}`} />
        <MetricCard
          label="Ambiente"
          value={data.health?.environment ?? "-"}
          hint={data.health?.debug ? "debug attivo" : "debug spento"}
        />
      </div>

      <article className="panel">
        <h3>Ultima partita importata</h3>
        {latestMatch ? (
          <div className="match-summary">
            <strong>
              {latestMatch.event_first_player ?? "-"} vs {latestMatch.event_second_player ?? "-"}
            </strong>
            <span>{formatDate(latestMatch.event_date)}</span>
            <span>{latestMatch.tournament_name ?? "Torneo non disponibile"}</span>
            <span>Score: {formatScore(latestMatch)}</span>
          </div>
        ) : (
          <EmptyState title="Nessuna partita trovata" message="Importa le partite o verifica la tabella fixture." />
        )}
      </article>

      <p className="note">
        I conteggi sono calcolati dagli endpoint lista disponibili. Per totali esatti serviranno endpoint aggregati backend.
      </p>
    </section>
  );
}
