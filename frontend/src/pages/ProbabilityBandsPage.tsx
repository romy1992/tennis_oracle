import { useCallback, useEffect, useState } from "react";

import { MetricCard } from "../components/MetricCard";
import { EmptyState, ErrorState, LoadingState } from "../components/Status";
import { apiClient } from "../services/apiClient";
import type {
  BandAnalysisSource,
  BandDimension,
  CalibrationMethod,
  MLModelVersion,
  ProbabilityBandAnalysis,
  ProbabilityBandBucket
} from "../types/api";
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

function BandTable({
  title,
  rows,
  bandDimension
}: {
  title: string;
  rows: ProbabilityBandBucket[];
  bandDimension: BandDimension;
}) {
  if (rows.length === 0) {
    return (
      <article className="panel">
        <h3>{title}</h3>
        <EmptyState title="Nessun dato" message="Nessuna fascia disponibile." />
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
              <th>Fascia</th>
              <th>N</th>
              <th>V/S</th>
              <th>Hit rate</th>
              <th>IC 95%</th>
              {bandDimension === "probability" ? (
                <>
                  <th>Prob. prevista</th>
                  <th>Prob. osservata</th>
                  <th>Gap cal.</th>
                </>
              ) : null}
              <th>Quota media</th>
              <th>Edge medio</th>
              <th>Profitto</th>
              <th>ROI</th>
              <th>Yield</th>
              <th>Campione</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
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
                {bandDimension === "probability" ? (
                  <>
                    <td>{formatPct(row.mean_predicted_pct)}</td>
                    <td>{formatPct(row.mean_observed_pct)}</td>
                    <td>{formatPct(row.calibration_gap_pct)}</td>
                  </>
                ) : null}
                <td>{formatNum(row.avg_odds)}</td>
                <td>{formatPct(row.avg_edge_pct)}</td>
                <td>{formatNum(row.profit)}</td>
                <td>{formatPct(row.roi_pct)}</td>
                <td>{formatPct(row.yield_pct)}</td>
                <td>{row.insufficient_sample ? "Basso" : "OK"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </article>
  );
}

export function ProbabilityBandsPage() {
  const [analysis, setAnalysis] = useState<ProbabilityBandAnalysis | null>(null);
  const [source, setSource] = useState<BandAnalysisSource>("live");
  const [bandDimension, setBandDimension] = useState<BandDimension>("probability");
  const [probabilityKind, setProbabilityKind] = useState<CalibrationMethod>("raw");
  const [modelVersion, setModelVersion] = useState<MLModelVersion>("v2");
  const [modelName, setModelName] = useState("logistic_regression");
  const [fromDate, setFromDate] = useState(() => daysAgoIso(180));
  const [toDate, setToDate] = useState(() => todayLocalISODate());
  const [nBins, setNBins] = useState(10);
  const [minBinSamples, setMinBinSamples] = useState(30);
  const [includeComparison, setIncludeComparison] = useState(false);
  const [groupByFold, setGroupByFold] = useState(false);
  const [groupByPeriod, setGroupByPeriod] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      setLoading(true);
      const response = await apiClient.getProbabilityBandAnalysis({
        source,
        band_dimension: bandDimension,
        probability_kind: source === "live" ? "raw" : probabilityKind,
        model_version: source === "live" ? undefined : modelVersion,
        model_name: source === "live" ? undefined : modelName,
        from: fromDate,
        to: toDate,
        n_bins: nBins,
        min_bin_samples: minBinSamples,
        include_comparison: includeComparison && source !== "live" && bandDimension === "probability",
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
    bandDimension,
    probabilityKind,
    modelVersion,
    modelName,
    fromDate,
    toDate,
    nBins,
    minBinSamples,
    includeComparison,
    groupByFold,
    groupByPeriod
  ]);

  useEffect(() => {
    void load();
  }, [load]);

  if (loading) {
    return <LoadingState title="Caricamento analisi fasce..." />;
  }

  if (error) {
    return <ErrorState title="Analisi fasce non disponibile" message={error} />;
  }

  if (!analysis) {
    return <EmptyState title="Nessun risultato" message="Prova a modificare i filtri." />;
  }

  const comparisonEntries = Object.entries(analysis.comparison ?? {});

  return (
    <div className="page-stack">
      <header className="page-header">
        <div>
          <h2>Analisi fasce probabilità / edge</h2>
          <p className="muted">
            Prestazioni per fasce configurabili. Sorgente attiva:{" "}
            <strong>{sourceLabel(analysis.source)}</strong>
            {analysis.probability_kind !== "raw" ? (
              <>
                {" "}
                · probabilità <strong>{analysis.probability_kind}</strong>
              </>
            ) : null}
          </p>
        </div>
      </header>

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
            Dimensione fascia
            <select
              value={bandDimension}
              onChange={(event) => setBandDimension(event.target.value as BandDimension)}
            >
              <option value="probability">Probabilità</option>
              <option value="edge">Edge</option>
            </select>
          </label>
          {source !== "live" ? (
            <>
              <label>
                Tipo probabilità
                <select
                  value={probabilityKind}
                  onChange={(event) =>
                    setProbabilityKind(event.target.value as CalibrationMethod)
                  }
                  disabled={bandDimension === "edge"}
                >
                  <option value="raw">Grezza</option>
                  <option value="platt">Platt</option>
                  <option value="isotonic">Isotonic</option>
                </select>
              </label>
              <label>
                Versione
                <select
                  value={modelVersion}
                  onChange={(event) => setModelVersion(event.target.value as MLModelVersion)}
                >
                  <option value="v1">v1</option>
                  <option value="v2">v2</option>
                  <option value="v3">v3</option>
                </select>
              </label>
              <label>
                Modello
                <select value={modelName} onChange={(event) => setModelName(event.target.value)}>
                  <option value="logistic_regression">logistic_regression</option>
                  <option value="random_forest">random_forest</option>
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
            N. fasce prob.
            <input
              type="number"
              min={2}
              max={50}
              value={nBins}
              onChange={(event) => setNBins(Number(event.target.value))}
            />
          </label>
          <label>
            Min. campione fascia
            <input
              type="number"
              min={1}
              value={minBinSamples}
              onChange={(event) => setMinBinSamples(Number(event.target.value))}
            />
          </label>
          {source !== "live" && bandDimension === "probability" ? (
            <label className="checkbox-label">
              <input
                type="checkbox"
                checked={includeComparison}
                onChange={(event) => setIncludeComparison(event.target.checked)}
              />
              Confronta raw / platt / isotonic
            </label>
          ) : null}
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
          value={formatPct(
            analysis.closed > 0 ? (analysis.won / analysis.closed) * 100 : null
          )}
        />
      </section>

      <BandTable
        title={`Fasce ${bandDimension === "probability" ? "probabilità" : "edge"} (${analysis.probability_kind})`}
        rows={analysis.bands}
        bandDimension={bandDimension}
      />

      {comparisonEntries.map(([kind, rows]) => (
        <BandTable
          key={kind}
          title={`Confronto — ${kind}`}
          rows={rows}
          bandDimension={bandDimension}
        />
      ))}

      {analysis.by_period.map((group) => (
        <BandTable
          key={group.period ?? "period"}
          title={`Periodo ${group.period ?? "-"}`}
          rows={group.bands}
          bandDimension={bandDimension}
        />
      ))}

      {analysis.by_fold.map((group) => (
        <BandTable
          key={group.fold_index ?? "fold"}
          title={`Fold ${group.fold_index ?? "-"}`}
          rows={group.bands}
          bandDimension={bandDimension}
        />
      ))}
    </div>
  );
}
