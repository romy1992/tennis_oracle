import { useEffect, useMemo, useState } from "react";

import { MarketTabs } from "../components/MarketTabs";
import { MetricCard } from "../components/MetricCard";
import { EmptyState, ErrorState, LoadingState } from "../components/Status";
import { apiClient } from "../services/apiClient";
import type {
  DailyPredictionStatsResponse,
  LiveDashboardMarket,
  PredictionSummaryResponse,
  PublishedLiveStatsSummary
} from "../types/api";
import {
  DEFAULT_LIVE_MARKET,
  internalVersionForMarket,
  marketLabel
} from "../utils/markets";
import { formatDate } from "../utils/tennis";

const DAYS_PAGE_SIZE = 5;

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
  const [market, setMarket] = useState<LiveDashboardMarket>(DEFAULT_LIVE_MARKET);
  const [dailyStats, setDailyStats] = useState<DailyPredictionStatsResponse | null>(null);
  const [summary, setSummary] = useState<PredictionSummaryResponse | null>(null);
  const [liveStats, setLiveStats] = useState<PublishedLiveStatsSummary | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [daysPage, setDaysPage] = useState(0);

  useEffect(() => {
    async function load() {
      try {
        setLoading(true);
        if (market === "match_winner") {
          const version = internalVersionForMarket(market);
          const [statsData, summaryData] = await Promise.all([
            apiClient.getDailyPredictionStats({
              model_version: version,
              from_day: 0
            }),
            apiClient.getPredictionSummary({
              model_version: version
            })
          ]);
          setDailyStats(statsData);
          setSummary(summaryData);
          setLiveStats(null);
        } else {
          const published = await apiClient.getPublishedLiveStats({
            market,
            include_archived: false,
            latest_only: true
          });
          setLiveStats(published);
          setDailyStats(null);
          setSummary(null);
        }
        setError(null);
      } catch (err) {
        setError(err instanceof Error ? err.message : "Errore inatteso.");
      } finally {
        setLoading(false);
      }
    }
    void load();
  }, [market]);

  useEffect(() => {
    setDaysPage(0);
  }, [market, dailyStats]);

  const daysNewestFirst = useMemo(() => {
    return [...(dailyStats?.days ?? [])].sort((left, right) =>
      right.date.localeCompare(left.date)
    );
  }, [dailyStats]);

  const daysTotalPages = Math.max(1, Math.ceil(daysNewestFirst.length / DAYS_PAGE_SIZE));
  const safeDaysPage = Math.min(daysPage, daysTotalPages - 1);
  const visibleDays = daysNewestFirst.slice(
    safeDaysPage * DAYS_PAGE_SIZE,
    safeDaysPage * DAYS_PAGE_SIZE + DAYS_PAGE_SIZE
  );

  if (loading && !summary && !liveStats) {
    return <LoadingState title="Caricamento statistiche..." />;
  }

  if (error && !summary && !liveStats) {
    return <ErrorState title="Statistiche non disponibili" message={error} />;
  }

  return (
    <section className="page">
      <header className="page-header">
        <div>
          <h2>Statistiche previsioni</h2>
          <p>
            Prestazioni per mercato. Vincitore partita: tutte le previsioni operative. 1° set e
            Over/Under: tip pubblicati nel registro live (fonte disponibile per questi mercati).
          </p>
        </div>
        <span className={`market-badge market-${market}`}>{marketLabel(market)}</span>
      </header>

      <MarketTabs
        value={market}
        onChange={setMarket}
        ariaLabel="Mercato statistiche previsioni"
        disabled={loading}
      />

      {error ? <ErrorState title="Aggiornamento parziale" message={error} /> : null}

      {market === "match_winner" && summary ? (
        <>
          <div className="metrics-grid">
            <MetricCard label="Previsioni totali" value={summary.predictions_total} />
            <MetricCard label="Vinte" value={summary.predictions_correct} />
            <MetricCard label="Perse" value={summary.predictions_lost} />
            <MetricCard label="Pending" value={summary.pending} />
            <MetricCard label="Accuracy globale" value={formatPct(summary.accuracy_pct)} />
            <MetricCard label="Previsioni con quota" value={summary.predictions_with_odds} />
            <MetricCard label="Quota media vinte" value={formatOdds(summary.avg_winning_odds)} />
            <MetricCard
              label="Profitto teorico"
              value={formatUnits(summary.theoretical_profit_units)}
            />
            <MetricCard label="ROI teorico" value={formatPct(summary.theoretical_roi_pct)} />
          </div>

          <article className="panel">
            <div className="panel-header">
              <h3>Andamento per giorno</h3>
              <span className="pill">5 giorni · dalla più recente</span>
            </div>
            <p className="note">
              Le colonne quota simulano una puntata da 1 unita su ogni previsione con quota
              disponibile: se la prediction e corretta il profitto e quota - 1, se e errata e -1.
            </p>

            {daysNewestFirst.length === 0 ? (
              <EmptyState
                title="Nessuna statistica"
                message="Le previsioni verranno aggregate quando ci saranno risultati importati."
              />
            ) : (
              <>
                {daysTotalPages > 1 ? (
                  <div className="pagination">
                    <button
                      type="button"
                      className="action-button"
                      disabled={safeDaysPage <= 0}
                      onClick={() => setDaysPage((current) => Math.max(0, current - 1))}
                      aria-label="Giorni più recenti"
                    >
                      ←
                    </button>
                    <span className="pagination-label">
                      {visibleDays.length
                        ? `${formatDate(visibleDays[0].date)} – ${formatDate(
                            visibleDays[visibleDays.length - 1].date
                          )}`
                        : "-"}{" "}
                      · {safeDaysPage + 1}/{daysTotalPages}
                    </span>
                    <button
                      type="button"
                      className="action-button"
                      disabled={safeDaysPage >= daysTotalPages - 1}
                      onClick={() =>
                        setDaysPage((current) => Math.min(daysTotalPages - 1, current + 1))
                      }
                      aria-label="Giorni precedenti"
                    >
                      →
                    </button>
                  </div>
                ) : null}
                <div className="table-wrap">
                  <table>
                    <thead>
                      <tr>
                        <th>Data</th>
                        <th>Totali</th>
                        <th>Risolte</th>
                        <th>Vinte</th>
                        <th>Perse</th>
                        <th>Pending</th>
                        <th>Accuracy</th>
                        <th>Con quota</th>
                        <th>Quota media</th>
                        <th>Profitto</th>
                        <th>ROI</th>
                      </tr>
                    </thead>
                    <tbody>
                      {visibleDays.map((day) => (
                        <tr key={day.date}>
                          <td>{formatDate(day.date)}</td>
                          <td>{day.predictions_total}</td>
                          <td>{day.predictions_resolved}</td>
                          <td>{day.predictions_correct}</td>
                          <td>{day.predictions_lost}</td>
                          <td>{day.pending}</td>
                          <td>{formatPct(day.accuracy_pct)}</td>
                          <td>{day.predictions_with_odds}</td>
                          <td>{formatOdds(day.avg_winning_odds)}</td>
                          <td>{formatUnits(day.theoretical_profit_units)}</td>
                          <td>{formatPct(day.theoretical_roi_pct)}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
                <p className="note">
                  Solo le prediction risolte contribuiscono a profitto e ROI.
                </p>
              </>
            )}
          </article>
        </>
      ) : null}

      {market !== "match_winner" && liveStats ? (
        <>
          <div className="metrics-grid">
            <MetricCard label="Tip pubblicati" value={String(liveStats.predictions_total)} />
            <MetricCard label="Chiusi" value={String(liveStats.closed)} />
            <MetricCard label="Aperti" value={String(liveStats.open)} />
            <MetricCard label="Void" value={String(liveStats.void)} />
            <MetricCard label="Hit rate" value={formatPct(liveStats.hit_rate_pct)} />
            <MetricCard label="Stake totale" value={formatUnits(liveStats.stake_total)} />
            <MetricCard label="Profitto" value={formatUnits(liveStats.profit)} />
            <MetricCard label="ROI" value={formatPct(liveStats.roi_pct)} />
            <MetricCard label="Yield" value={formatPct(liveStats.yield_pct)} />
          </div>
          {liveStats.predictions_total === 0 ? (
            <EmptyState
              title={`Nessun tip · ${marketLabel(market)}`}
              message="Pubblica tip di questo mercato nel registro live per vedere le metriche."
            />
          ) : (
            <p className="note">
              Fonte: registro pubblicazioni immutabile (stesso settlement di Statistiche live). Per
              il dettaglio fasce/segmenti usa le pagine dedicate filtrando questo mercato.
            </p>
          )}
        </>
      ) : null}
    </section>
  );
}
