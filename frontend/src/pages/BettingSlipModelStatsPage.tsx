import { useEffect, useMemo, useState } from "react";

import { MetricCard } from "../components/MetricCard";
import { EmptyState, ErrorState, LoadingState } from "../components/Status";
import { apiClient } from "../services/apiClient";
import type { BettingSlipModelStatsResponse, BettingSlipModelStatsRow } from "../types/api";
import { formatDate, todayLocalISODate } from "../utils/tennis";

const STAKE_PRESETS = [1, 5, 10, 25, 50];

type PeriodMode = "last30" | "allTime" | "manual";
type SortKey = "slip_win_rate_pct" | "theoretical_roi_pct" | "slips_total";
type SortDirection = "asc" | "desc";

function todayIso() {
  return todayLocalISODate();
}

function daysAgoIso(days: number) {
  const value = new Date();
  value.setDate(value.getDate() - days);
  return todayLocalISODate(value);
}

function formatPct(value: number | null | undefined) {
  if (value === null || value === undefined) return "-";
  return `${value.toLocaleString("it-IT", { maximumFractionDigits: 1 })}%`;
}

function formatMoney(value: number | null | undefined) {
  if (value === null || value === undefined) return "-";
  return `${value.toLocaleString("it-IT", {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2
  })} €`;
}

function sortValue(row: BettingSlipModelStatsRow, key: SortKey) {
  return row[key] ?? Number.NEGATIVE_INFINITY;
}

function SortButton({
  label,
  sortKey,
  activeKey,
  direction,
  onSort
}: {
  label: string;
  sortKey: SortKey;
  activeKey: SortKey;
  direction: SortDirection;
  onSort: (key: SortKey) => void;
}) {
  const marker = activeKey === sortKey ? (direction === "desc" ? " ↓" : " ↑") : "";
  return (
    <button type="button" className="table-sort-button" onClick={() => onSort(sortKey)}>
      {label}
      {marker}
    </button>
  );
}

export function BettingSlipModelStatsPage() {
  const [stats, setStats] = useState<BettingSlipModelStatsResponse | null>(null);
  const [periodMode, setPeriodMode] = useState<PeriodMode>("last30");
  const [fromDate, setFromDate] = useState(() => daysAgoIso(30));
  const [toDate, setToDate] = useState(() => todayIso());
  const [stake, setStake] = useState(10);
  const [sortKey, setSortKey] = useState<SortKey>("slip_win_rate_pct");
  const [sortDirection, setSortDirection] = useState<SortDirection>("desc");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    async function load() {
      try {
        setLoading(true);
        const data = await apiClient.getBettingSlipModelStats({
          from: periodMode === "last30" ? daysAgoIso(30) : periodMode === "manual" ? fromDate : undefined,
          to: periodMode === "last30" ? todayIso() : periodMode === "manual" ? toDate : undefined,
          all_time: periodMode === "allTime",
          stake
        });
        setStats(data);
        setError(null);
      } catch (err) {
        setError(err instanceof Error ? err.message : "Errore inatteso.");
      } finally {
        setLoading(false);
      }
    }
    void load();
  }, [periodMode, fromDate, toDate, stake]);

  const sortedRows = useMemo(() => {
    const direction = sortDirection === "desc" ? -1 : 1;
    return [...(stats?.rows ?? [])].sort((left, right) => {
      const primary = sortValue(left, sortKey) - sortValue(right, sortKey);
      if (primary !== 0) return primary * direction;
      return `${left.model_version}-${left.model_name}`.localeCompare(`${right.model_version}-${right.model_name}`);
    });
  }, [stats, sortDirection, sortKey]);

  const totals = useMemo(() => {
    const rows = stats?.rows ?? [];
    const slipsWon = rows.reduce((total, row) => total + row.slips_won, 0);
    const slipsLost = rows.reduce((total, row) => total + row.slips_lost, 0);
    const picksWon = rows.reduce((total, row) => total + row.picks_won, 0);
    const picksLost = rows.reduce((total, row) => total + row.picks_lost, 0);
    const profit = rows.reduce((total, row) => total + row.theoretical_profit_units, 0);
    const resolvedSlips = slipsWon + slipsLost;
    const resolvedPicks = picksWon + picksLost;
    return {
      slipsTotal: rows.reduce((total, row) => total + row.slips_total, 0),
      slipsPending: rows.reduce((total, row) => total + row.slips_pending, 0),
      slipWinRate: resolvedSlips ? (slipsWon / resolvedSlips) * 100 : null,
      pickHitRate: resolvedPicks ? (picksWon / resolvedPicks) * 100 : null,
      profit,
      roi: resolvedSlips ? (profit / (resolvedSlips * (stats?.stake ?? stake))) * 100 : null
    };
  }, [stats, stake]);

  function handleSort(nextKey: SortKey) {
    if (nextKey === sortKey) {
      setSortDirection((current) => (current === "desc" ? "asc" : "desc"));
      return;
    }
    setSortKey(nextKey);
    setSortDirection("desc");
  }

  if (loading) {
    return <LoadingState title="Caricamento statistiche schedine..." />;
  }

  if (error) {
    return <ErrorState title="Statistiche schedine non disponibili" message={error} />;
  }

  return (
    <section className="page">
      <header className="page-header">
        <div>
          <h2>Statistiche schedine</h2>
          <p>
            Confronto aggregato per versione e modello dal{" "}
            {stats ? formatDate(stats.from_date) : "-"} al {stats ? formatDate(stats.to_date) : "-"}.
          </p>
        </div>
      </header>

      <article className="panel">
        <div className="panel-header">
          <h3>Periodo e stake</h3>
          <span className="pill">pending esclusi dalle percentuali</span>
        </div>
        <div className="stats-filter-panel">
          <div className="tab-list">
            <button
              type="button"
              className={periodMode === "last30" ? "active" : undefined}
              onClick={() => setPeriodMode("last30")}
            >
              Ultimi 30 giorni
            </button>
            <button
              type="button"
              className={periodMode === "allTime" ? "active" : undefined}
              onClick={() => setPeriodMode("allTime")}
            >
              All time
            </button>
            <button
              type="button"
              className={periodMode === "manual" ? "active" : undefined}
              onClick={() => setPeriodMode("manual")}
            >
              Date manuali
            </button>
          </div>

          {periodMode === "manual" ? (
            <div className="filters-grid compact two-columns">
              <label>
                Da
                <input type="date" value={fromDate} onChange={(event) => setFromDate(event.target.value)} />
              </label>
              <label>
                A
                <input type="date" value={toDate} onChange={(event) => setToDate(event.target.value)} />
              </label>
            </div>
          ) : null}

          <div className="stake-controls">
            <label htmlFor="model-stats-stake">Simula puntata</label>
            <input
              id="model-stats-stake"
              type="number"
              min={0.01}
              step={0.5}
              value={stake}
              onChange={(event) => setStake(Number(event.target.value) || 1)}
            />
            {STAKE_PRESETS.map((preset) => (
              <button
                key={preset}
                type="button"
                className={stake === preset ? "pill active" : "pill"}
                onClick={() => setStake(preset)}
              >
                {preset} €
              </button>
            ))}
          </div>
        </div>
      </article>

      <div className="metrics-grid">
        <MetricCard label="Schedine totali" value={totals.slipsTotal} />
        <MetricCard label="Pending" value={totals.slipsPending} />
        <MetricCard label="Riuscita schedine" value={formatPct(totals.slipWinRate)} />
        <MetricCard label="Riuscita pick" value={formatPct(totals.pickHitRate)} />
        <MetricCard label="Profitto teorico" value={formatMoney(totals.profit)} />
        <MetricCard label="ROI teorico" value={formatPct(totals.roi)} />
      </div>

      <article className="panel">
        <div className="panel-header">
          <h3>Confronto modelli</h3>
          <span className="pill">{sortedRows.length} combinazioni</span>
        </div>

        {sortedRows.length === 0 ? (
          <EmptyState
            title="Nessuna schedina nel periodo"
            message="Cambia periodo o genera schedine per visualizzare il confronto."
          />
        ) : (
          <div className="table-wrap">
            <table className="model-stats-table">
              <thead>
                <tr>
                  <th>Versione</th>
                  <th>Modello</th>
                  <th>
                    <SortButton
                      label="Schedine totali"
                      sortKey="slips_total"
                      activeKey={sortKey}
                      direction={sortDirection}
                      onSort={handleSort}
                    />
                  </th>
                  <th>Vinte</th>
                  <th>Perse</th>
                  <th>Pending</th>
                  <th>
                    <SortButton
                      label="% schedine"
                      sortKey="slip_win_rate_pct"
                      activeKey={sortKey}
                      direction={sortDirection}
                      onSort={handleSort}
                    />
                  </th>
                  <th>Pick totali</th>
                  <th>Pick vinte</th>
                  <th>Pick perse</th>
                  <th>Pick pending</th>
                  <th>% pick</th>
                  <th>Profitto</th>
                  <th>
                    <SortButton
                      label="ROI"
                      sortKey="theoretical_roi_pct"
                      activeKey={sortKey}
                      direction={sortDirection}
                      onSort={handleSort}
                    />
                  </th>
                  <th>Prima data</th>
                  <th>Ultima data</th>
                </tr>
              </thead>
              <tbody>
                {sortedRows.map((row) => (
                  <tr key={`${row.model_version}-${row.model_name}`}>
                    <td>{row.model_version}</td>
                    <td>{row.model_name}</td>
                    <td>{row.slips_total}</td>
                    <td>{row.slips_won}</td>
                    <td>{row.slips_lost}</td>
                    <td>
                      <span className="slip-status-badge pending">{row.slips_pending}</span>
                    </td>
                    <td>{formatPct(row.slip_win_rate_pct)}</td>
                    <td>{row.picks_total}</td>
                    <td>{row.picks_won}</td>
                    <td>{row.picks_lost}</td>
                    <td>
                      <span className="slip-status-badge pending">{row.picks_pending}</span>
                    </td>
                    <td>{formatPct(row.pick_hit_rate_pct)}</td>
                    <td className={row.theoretical_profit_units >= 0 ? "positive-value" : "negative-value"}>
                      {formatMoney(row.theoretical_profit_units)}
                    </td>
                    <td>{formatPct(row.theoretical_roi_pct)}</td>
                    <td>{formatDate(row.first_date)}</td>
                    <td>{formatDate(row.last_date)}</td>
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
