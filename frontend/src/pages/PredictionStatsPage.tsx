import { useEffect, useState } from "react";

import { MetricCard } from "../components/MetricCard";
import { EmptyState, ErrorState, LoadingState } from "../components/Status";
import { apiClient } from "../services/apiClient";
import type {
  DailyPredictionStatsResponse,
  MLModelVersion,
  PredictionSummaryResponse
} from "../types/api";
import { formatDate } from "../utils/tennis";

function formatPct(value: number | null | undefined) {
  if (value === null || value === undefined) return "-";
  return `${value.toLocaleString("it-IT", { maximumFractionDigits: 1 })}%`;
}

function formatOdds(value: number | null | undefined) {
  if (value === null || value === undefined) return "-";
  return value.toLocaleString("it-IT", {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2
  });
}

function formatUnits(value: number | null | undefined) {
  if (value === null || value === undefined) return "-";
  return value.toLocaleString("it-IT", {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2
  });
}

export function PredictionStatsPage() {
  const [selectedVersion, setSelectedVersion] = useState<MLModelVersion>("v2");
  const [dailyStats, setDailyStats] = useState<DailyPredictionStatsResponse | null>(null);
  const [summary, setSummary] = useState<PredictionSummaryResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    async function load() {
      try {
        setLoading(true);
        const [statsData, summaryData] = await Promise.all([
          apiClient.getDailyPredictionStats({
            model_version: selectedVersion,
            from_day: 0
          }),
          apiClient.getPredictionSummary({ model_version: selectedVersion })
        ]);
        setDailyStats(statsData);
        setSummary(summaryData);
        setError(null);
      } catch (err) {
        setError(err instanceof Error ? err.message : "Errore inatteso.");
      } finally {
        setLoading(false);
      }
    }
    void load();
  }, [selectedVersion]);

  if (loading) {
    return <LoadingState title="Caricamento statistiche..." />;
  }

  if (error) {
    return <ErrorState title="Statistiche non disponibili" message={error} />;
  }

  const chronologicalDays = [...(dailyStats?.days ?? [])].sort((left, right) =>
    left.date.localeCompare(right.date)
  );

  return (
    <section className="page">
      <header className="page-header">
        <div>
          <h2>Statistiche previsioni</h2>
          <p>
            Storico completo delle previsioni salvate confrontate con i risultati importati.
          </p>
        </div>
        <label className="filters-grid" style={{ minWidth: 280 }}>
          <span>Versione modello</span>
          <select
            id="prediction-stats-model-version"
            value={selectedVersion}
            onChange={(event) => setSelectedVersion(event.target.value as MLModelVersion)}
          >
            <option value="v1">v1</option>
            <option value="v2">v2</option>
          </select>
        </label>
      </header>

      <div className="metrics-grid">
        <MetricCard label="Previsioni totali" value={summary?.predictions_total ?? 0} />
        <MetricCard label="Vinte" value={summary?.predictions_correct ?? 0} />
        <MetricCard label="Perse" value={summary?.predictions_lost ?? 0} />
        <MetricCard label="Pending" value={summary?.pending ?? 0} />
        <MetricCard label="Accuracy globale" value={formatPct(summary?.accuracy_pct)} />
        <MetricCard label="Previsioni con quota" value={summary?.predictions_with_odds ?? 0} />
        <MetricCard label="Quota media vinte" value={formatOdds(summary?.avg_winning_odds)} />
        <MetricCard label="Profitto teorico" value={formatUnits(summary?.theoretical_profit_units)} />
        <MetricCard label="ROI teorico" value={formatPct(summary?.theoretical_roi_pct)} />
      </div>

      <article className="panel">
        <div className="panel-header">
          <h3>Andamento per giorno</h3>
          <span className="pill">solo prediction risolte contribuiscono a profitto e ROI</span>
        </div>
        <p className="note">
          Le colonne quota simulano una puntata da 1 unita su ogni previsione con quota
          disponibile: se la prediction e corretta il profitto e quota - 1, se e errata e -1.
          Restano a 0 o "-" quando quel giorno non ci sono previsioni risolte con odds salvate.
        </p>

        {chronologicalDays.length === 0 ? (
          <EmptyState
            title="Nessuna statistica"
            message="Le previsioni verranno aggregate quando ci saranno risultati importati."
          />
        ) : (
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Day</th>
                  <th>Data</th>
                  <th>Totali</th>
                  <th>Vinte</th>
                  <th>Perse</th>
                  <th>Pending</th>
                  <th>Accuracy</th>
                  <th>Con quota</th>
                  <th>Quota media predetto</th>
                  <th>Profitto</th>
                  <th>ROI</th>
                </tr>
              </thead>
              <tbody>
                {chronologicalDays.map((day, index) => (
                  <tr key={day.day_offset}>
                    <td>{index}</td>
                    <td>{formatDate(day.date)}</td>
                    <td>{day.predictions_total}</td>
                    <td>{day.predictions_correct}</td>
                    <td>{day.predictions_lost}</td>
                    <td>{day.pending}</td>
                    <td>{formatPct(day.accuracy_pct)}</td>
                    <td>{day.predictions_with_odds}</td>
                    <td>{formatOdds(day.avg_predicted_winner_odds)}</td>
                    <td>{formatUnits(day.theoretical_profit_units)}</td>
                    <td>{formatPct(day.theoretical_roi_pct)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </article>

      <article className="panel">
        <div className="panel-header">
          <h3>Breakdown modello</h3>
          <span className="pill">{selectedVersion}</span>
        </div>

        {!summary || summary.breakdown.length === 0 ? (
          <EmptyState title="Nessun breakdown" />
        ) : (
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Versione</th>
                  <th>Modello</th>
                  <th>Totali</th>
                  <th>Vinte</th>
                  <th>Perse</th>
                  <th>Pending</th>
                  <th>Accuracy</th>
                </tr>
              </thead>
              <tbody>
                {summary.breakdown.map((item) => (
                  <tr key={`${item.model_version}-${item.model_name ?? "unknown"}`}>
                    <td>{item.model_version}</td>
                    <td>{item.model_name ?? "-"}</td>
                    <td>{item.predictions_total}</td>
                    <td>{item.predictions_correct}</td>
                    <td>{item.predictions_lost}</td>
                    <td>{item.pending}</td>
                    <td>{formatPct(item.accuracy_pct)}</td>
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
