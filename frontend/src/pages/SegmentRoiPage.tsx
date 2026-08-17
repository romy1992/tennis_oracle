import { useCallback, useEffect, useState } from "react";

import { MarketTabs } from "../components/MarketTabs";
import { MetricCard } from "../components/MetricCard";
import { EmptyState, ErrorState, LoadingState } from "../components/Status";
import { apiClient } from "../services/apiClient";
import type {
  BandAnalysisSource,
  LiveDashboardMarket,
  MLModelVersion,
  SegmentDimension,
  SegmentRoiAnalysis,
  SegmentRoiBucket
} from "../types/api";
import { DEFAULT_LIVE_MARKET, marketLabel } from "../utils/markets";
import { DEFAULT_MODEL_VERSION } from "../utils/modelVersion";
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

function sourceLabel(source: BandAnalysisSource) {
  switch (source) {
    case "live":
      return "Live (PublishedPrediction)";
    case "walk_forward":
      return "Walk-forward OOS";
    case "backtest":
      return "Backtest OOS";
    default:
      return source;
  }
}

const SEGMENT_DIMENSION_LABELS: Record<SegmentDimension, string> = {
  surface: "Superficie",
  tournament: "Torneo",
  circuit: "Circuito",
  level: "Livello",
  round: "Turno",
  favorite_role: "Favorito / sfavorito",
  odds_band: "Fascia quota",
  bookmaker: "Bookmaker",
  model: "Modello",
  version: "Versione",
  period: "Periodo"
};

function SegmentTable({ title, rows }: { title: string; rows: SegmentRoiBucket[] }) {
  if (rows.length === 0) {
    return (
      <article className="panel">
        <h3>{title}</h3>
        <EmptyState title="Nessun dato" message="Nessun segmento disponibile." />
      </article>
    );
  }

  const populated = rows.filter((row) => row.closed > 0);

  return (
    <article className="panel">
      <h3>{title}</h3>
      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <th>Segmento</th>
              <th>N</th>
              <th>V/S</th>
              <th>Hit rate</th>
              <th>IC hit 95%</th>
              <th>Quota media</th>
              <th>Edge medio</th>
              <th>Profitto</th>
              <th>ROI</th>
              <th>IC ROI 95%</th>
              <th>Yield</th>
              <th>Drawdown</th>
              <th>Campione</th>
            </tr>
          </thead>
          <tbody>
            {(populated.length > 0 ? populated : rows).map((row) => (
              <tr
                key={row.key}
                className={row.insufficient_sample ? "row-warning" : undefined}
                title={
                  row.insufficient_sample
                    ? "Campione insufficiente per inferenze affidabili"
                    : undefined
                }
              >
                <td>{row.label}</td>
                <td>{row.closed}</td>
                <td>
                  {row.won}/{row.lost}
                </td>
                <td>{formatPct(row.hit_rate_pct)}</td>
                <td>
                  {formatPct(row.hit_rate_ci_lower_pct)} – {formatPct(row.hit_rate_ci_upper_pct)}
                </td>
                <td>{formatNum(row.avg_odds)}</td>
                <td>{formatPct(row.avg_edge_pct)}</td>
                <td>{formatNum(row.profit)}</td>
                <td>{formatPct(row.roi_pct)}</td>
                <td>
                  {formatPct(row.roi_ci_lower_pct)} – {formatPct(row.roi_ci_upper_pct)}
                </td>
                <td>{formatPct(row.yield_pct)}</td>
                <td>{formatNum(row.max_drawdown)}</td>
                <td>{row.insufficient_sample ? "Basso" : "OK"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </article>
  );
}

export function SegmentRoiPage() {
  const [analysis, setAnalysis] = useState<SegmentRoiAnalysis | null>(null);
  const [source, setSource] = useState<BandAnalysisSource>("live");
  const [segmentDimension, setSegmentDimension] = useState<SegmentDimension>("surface");
  const [modelVersion, setModelVersion] = useState<MLModelVersion>(DEFAULT_MODEL_VERSION);
  const [modelName, setModelName] = useState("voting_ensemble");
  const [market, setMarket] = useState<LiveDashboardMarket>(DEFAULT_LIVE_MARKET);
  const [fromDate, setFromDate] = useState(() => daysAgoIso(180));
  const [toDate, setToDate] = useState(() => todayLocalISODate());
  const [minSegmentSamples, setMinSegmentSamples] = useState(30);
  const [groupByFold, setGroupByFold] = useState(false);
  const [groupByPeriod, setGroupByPeriod] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      setLoading(true);
      const response = await apiClient.getSegmentRoiAnalysis({
        source,
        segment_dimension: segmentDimension,
        model_version: source === "live" ? undefined : modelVersion,
        model_name: source === "live" ? undefined : modelName,
        market: source === "live" ? market : undefined,
        include_archived: source === "live" ? false : undefined,
        from: fromDate,
        to: toDate,
        min_segment_samples: minSegmentSamples,
        group_by_fold: groupByFold && source === "walk_forward",
        group_by_period: groupByPeriod
      });
      setAnalysis(response);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Errore inatteso.");
      setAnalysis(null);
    } finally {
      setLoading(false);
    }
  }, [
    source,
    segmentDimension,
    modelVersion,
    modelName,
    market,
    fromDate,
    toDate,
    minSegmentSamples,
    groupByFold,
    groupByPeriod
  ]);

  useEffect(() => {
    void load();
  }, [load]);

  if (loading && !analysis) {
    return <LoadingState title="Caricamento ROI per segmento..." />;
  }

  if (error && !analysis) {
    return <ErrorState title="Analisi segmenti non disponibile" message={error} />;
  }

  if (!analysis) {
    return <EmptyState title="Nessun risultato" message="Prova a modificare i filtri." />;
  }

  return (
    <div className="page-stack">
      <header className="page-header">
        <div>
          <h2>ROI per segmento</h2>
          <p className="muted">
            Prestazioni per {SEGMENT_DIMENSION_LABELS[analysis.segment_dimension].toLowerCase()}.
            Sorgente attiva: <strong>{sourceLabel(analysis.source)}</strong>
            {analysis.source === "live" ? (
              <>
                {" "}
                · mercato <strong>{marketLabel(analysis.market ?? market)}</strong>
              </>
            ) : null}
          </p>
        </div>
        {source === "live" ? (
          <span className={`market-badge market-${market}`}>{marketLabel(market)}</span>
        ) : null}
      </header>

      {source === "live" ? (
        <MarketTabs
          value={market}
          onChange={setMarket}
          ariaLabel="Mercato ROI per segmento"
          disabled={loading}
        />
      ) : null}

      <article className="panel filters-panel">
        <h3>Filtri</h3>
        <div className="filters-grid">
          <label>
            Sorgente
            <select
              value={source}
              onChange={(event) => setSource(event.target.value as BandAnalysisSource)}
            >
              <option value="live">Live</option>
              <option value="walk_forward">Walk-forward</option>
              <option value="backtest">Backtest</option>
            </select>
          </label>
          <label>
            Segmento
            <select
              value={segmentDimension}
              onChange={(event) => setSegmentDimension(event.target.value as SegmentDimension)}
            >
              {(Object.keys(SEGMENT_DIMENSION_LABELS) as SegmentDimension[]).map((key) => (
                <option key={key} value={key}>
                  {SEGMENT_DIMENSION_LABELS[key]}
                </option>
              ))}
            </select>
          </label>
          {source !== "live" ? (
            <>
              <label>
                Serie storica (Vincitore partita)
                <select
                  value={modelVersion}
                  onChange={(event) => setModelVersion(event.target.value as MLModelVersion)}
                >
                  <option value="v4">Vincitore partita (attuale)</option>
                  <option value="v3">Vincitore partita (archivio)</option>
                  <option value="v2">Vincitore partita (archivio B)</option>
                  <option value="v1">Vincitore partita (archivio C)</option>
                </select>
              </label>
              <label>
                Modello
                <select value={modelName} onChange={(event) => setModelName(event.target.value)}>
                  <option value="voting_ensemble">Ensemble</option>
                  <option value="logistic_regression">Logistic regression</option>
                  <option value="random_forest">Random forest</option>
                </select>
              </label>
            </>
          ) : null}
          <label>
            Da
            <input type="date" value={fromDate} onChange={(event) => setFromDate(event.target.value)} />
          </label>
          <label>
            A
            <input type="date" value={toDate} onChange={(event) => setToDate(event.target.value)} />
          </label>
          <label>
            Min. campione segmento
            <input
              type="number"
              min={1}
              value={minSegmentSamples}
              onChange={(event) => setMinSegmentSamples(Number(event.target.value))}
            />
          </label>
          {source === "walk_forward" ? (
            <label className="checkbox-label">
              <input
                type="checkbox"
                checked={groupByFold}
                onChange={(event) => setGroupByFold(event.target.checked)}
              />
              Raggruppa per fold
            </label>
          ) : null}
          <label className="checkbox-label">
            <input
              type="checkbox"
              checked={groupByPeriod}
              onChange={(event) => setGroupByPeriod(event.target.checked)}
            />
            Raggruppa per periodo
          </label>
        </div>
        <button type="button" className="action-button" onClick={() => void load()}>
          Aggiorna
        </button>
      </article>

      {analysis.notes.length > 0 ? (
        <article className="panel info-panel">
          <ul>
            {analysis.notes.map((note) => (
              <li key={note}>{note}</li>
            ))}
          </ul>
        </article>
      ) : null}

      <section className="metrics-grid">
        <MetricCard label="Pronostici chiusi" value={String(analysis.closed)} />
        <MetricCard label="Vittorie" value={String(analysis.won)} />
        <MetricCard label="Sconfitte" value={String(analysis.lost)} />
        <MetricCard
          label="Hit rate"
          value={formatPct(analysis.closed > 0 ? (analysis.won / analysis.closed) * 100 : null)}
        />
      </section>

      <SegmentTable
        title={`ROI per ${SEGMENT_DIMENSION_LABELS[analysis.segment_dimension].toLowerCase()}`}
        rows={analysis.segments}
      />

      {analysis.by_period.map((group) => (
        <SegmentTable
          key={group.period ?? "period"}
          title={`Periodo ${group.period ?? "-"}`}
          rows={group.segments}
        />
      ))}

      {analysis.by_fold.map((group) => (
        <SegmentTable
          key={group.fold_index ?? "fold"}
          title={`Fold ${group.fold_index ?? "-"}`}
          rows={group.segments}
        />
      ))}
    </div>
  );
}
