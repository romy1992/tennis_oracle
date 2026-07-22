import { useEffect, useState } from "react";

import { MetricCard } from "../components/MetricCard";
import { EmptyState, ErrorState, LoadingState } from "../components/Status";
import { apiClient } from "../services/apiClient";
import type { PublishedLiveStatsBucket, PublishedLiveStatsSummary } from "../types/api";
import { todayLocalISODate } from "../utils/tennis";

function daysAgoIso(days: number) {
  const value = new Date();
  value.setDate(value.getDate() - days);
  return todayLocalISODate(value);
}

function formatPct(value: number | null | undefined) {
  if (value === null || value === undefined) return "-";
  return `${value.toLocaleString("it-IT", { maximumFractionDigits: 2 })}%`;
}

function formatNum(value: number | null | undefined, digits = 2) {
  if (value === null || value === undefined) return "-";
  return value.toLocaleString("it-IT", {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits
  });
}

function DistributionTable({
  title,
  rows
}: {
  title: string;
  rows: PublishedLiveStatsBucket[];
}) {
  if (rows.length === 0) {
    return (
      <article className="panel">
        <h3>{title}</h3>
        <EmptyState title="Nessun dato" message="Nessuna distribuzione disponibile." />
      </article>
    );
  }

  return (
    <article className="panel">
      <h3>{title}</h3>
      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <th>Gruppo</th>
              <th>Totale</th>
              <th>Chiusi</th>
              <th>Aperti</th>
              <th>Void</th>
              <th>Hit rate</th>
              <th>Stake</th>
              <th>Profitto</th>
              <th>ROI</th>
              <th>Yield</th>
              <th>Quota media</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <tr key={row.key}>
                <td>{row.label}</td>
                <td>{row.predictions_total}</td>
                <td>{row.closed}</td>
                <td>{row.open}</td>
                <td>{row.void}</td>
                <td>{formatPct(row.hit_rate_pct)}</td>
                <td>{formatNum(row.stake_total)}</td>
                <td>{formatNum(row.profit)}</td>
                <td>{formatPct(row.roi_pct)}</td>
                <td>{formatPct(row.yield_pct)}</td>
                <td>{formatNum(row.avg_odds)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </article>
  );
}

export function PublishedLiveStatsPage() {
  const [stats, setStats] = useState<PublishedLiveStatsSummary | null>(null);
  const [fromDate, setFromDate] = useState(() => daysAgoIso(90));
  const [toDate, setToDate] = useState(() => todayLocalISODate());
  const [latestOnly, setLatestOnly] = useState(true);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    async function load() {
      try {
        setLoading(true);
        const response = await apiClient.getPublishedLiveStats({
          from: fromDate,
          to: toDate,
          latest_only: latestOnly
        });
        setStats(response);
        setError(null);
      } catch (err) {
        setError(err instanceof Error ? err.message : "Errore inatteso.");
      } finally {
        setLoading(false);
      }
    }
    void load();
  }, [fromDate, toDate, latestOnly]);

  if (loading) {
    return <LoadingState title="Caricamento statistiche live..." />;
  }

  if (error) {
    return <ErrorState title="Statistiche live non disponibili" message={error} />;
  }

  if (!stats || stats.predictions_total === 0) {
    return (
      <section className="page">
        <header className="page-header">
          <div>
            <h2>Statistiche live pubblicazioni</h2>
            <p>
              KPI dal registro immutabile (non da training, backtest o previsioni operative).
            </p>
          </div>
        </header>
        <EmptyState
          title="Nessuna pubblicazione"
          message="Pubblica tip nel registro immutabile per vedere hit rate, ROI, drawdown e distribuzioni."
        />
      </section>
    );
  }

  return (
    <section className="page">
      <header className="page-header">
        <div>
          <h2>Statistiche live pubblicazioni</h2>
          <p>
            Solo tip pubblicati nel ledger immutabile. Settlement a lettura; void esclusi da hit
            rate / ROI / yield.
          </p>
        </div>
      </header>

      <div className="filters-grid compact">
        <label>
          Da
          <input type="date" value={fromDate} onChange={(e) => setFromDate(e.target.value)} />
        </label>
        <label>
          A
          <input type="date" value={toDate} onChange={(e) => setToDate(e.target.value)} />
        </label>
        <label>
          <input
            type="checkbox"
            checked={latestOnly}
            onChange={(e) => setLatestOnly(e.target.checked)}
          />{" "}
          Solo versione più recente
        </label>
      </div>

      <div className="metrics-grid">
        <MetricCard label="Pronostici totali" value={String(stats.predictions_total)} />
        <MetricCard label="Chiusi" value={String(stats.closed)} />
        <MetricCard label="Aperti" value={String(stats.open)} />
        <MetricCard label="Void" value={String(stats.void)} />
        <MetricCard label="Hit rate" value={formatPct(stats.hit_rate_pct)} />
        <MetricCard label="Stake totale" value={formatNum(stats.stake_total)} />
        <MetricCard label="Profitto" value={formatNum(stats.profit)} />
        <MetricCard label="ROI" value={formatPct(stats.roi_pct)} />
        <MetricCard label="Yield" value={formatPct(stats.yield_pct)} />
        <MetricCard label="Quota media" value={formatNum(stats.avg_odds)} />
        <MetricCard label="Max drawdown" value={formatNum(stats.max_drawdown)} />
        <MetricCard
          label="Serie +/-"
          value={`${stats.max_winning_streak} / ${stats.max_losing_streak}`}
        />
      </div>

      <DistributionTable title="Per modello" rows={stats.by_model} />
      <DistributionTable title="Per quota" rows={stats.by_odds} />
      <DistributionTable title="Per edge" rows={stats.by_edge} />
      <DistributionTable title="Per superficie" rows={stats.by_surface} />
      <DistributionTable title="Per periodo (mese evento)" rows={stats.by_period} />
    </section>
  );
}
