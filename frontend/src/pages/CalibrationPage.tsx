import { useEffect, useMemo, useState } from "react";

import { MetricCard } from "../components/MetricCard";
import { LongRunningJobProgress } from "../components/LongRunningJobProgress";
import { EmptyState, ErrorState, LoadingState } from "../components/Status";
import { apiClient, ApiError } from "../services/apiClient";
import type {
  CalibrationResult,
  CalibrationRun,
  CalibrationRunListItem,
  MLModelVersion
} from "../types/api";

function formatPct(value: number | null | undefined) {
  if (value === null || value === undefined) return "-";
  return `${(value * 100).toLocaleString("it-IT", { maximumFractionDigits: 1 })}%`;
}

function formatNum(value: number | null | undefined, digits = 4) {
  if (value === null || value === undefined) return "-";
  return value.toLocaleString("it-IT", {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits
  });
}

function formatDateTime(value: string | null | undefined) {
  if (!value) return "-";
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return value;
  return parsed.toLocaleString("it-IT");
}

function statusLabel(status: string) {
  switch (status) {
    case "completed":
      return "Completata";
    case "completed_with_errors":
      return "Completata con errori";
    case "running":
      return "In corso";
    case "pending":
      return "In coda";
    case "failed":
      return "Fallita";
    case "cancelled":
      return "Annullata";
    default:
      return status;
  }
}

type ReliabilityBin = {
  bin_index: number;
  bin_start: number;
  bin_end: number;
  count: number;
  mean_predicted: number | null;
  mean_actual: number | null;
  calibration_gap: number | null;
  insufficient_sample: boolean;
};

type MethodMetrics = {
  brier_score?: number | null;
  log_loss?: number | null;
  ece?: number | null;
  mce?: number | null;
  n_samples?: number;
  reliability_bins?: ReliabilityBin[];
};

function metricFromAggregate(
  result: CalibrationResult | undefined,
  method: string,
  key: keyof MethodMetrics
): number | null {
  const aggregate = result?.aggregate;
  if (!aggregate || typeof aggregate !== "object") return null;
  const methodMetrics = (aggregate as Record<string, MethodMetrics>)[method];
  if (!methodMetrics) return null;
  const value = methodMetrics[key];
  return typeof value === "number" ? value : null;
}

const ACTIVE_RUN_STATUSES = new Set(["pending", "running"]);
const RUN_POLL_INTERVAL_MS = 12_000;

function syncListItemProgress(
  item: CalibrationRunListItem,
  detail: CalibrationRun
): CalibrationRunListItem {
  return {
    ...item,
    status: detail.status,
    finished_at: detail.finished_at,
    duration_seconds: detail.duration_seconds,
    current_phase: detail.current_phase,
    progress_pct: detail.progress_pct,
    progress_current: detail.progress_current,
    progress_total: detail.progress_total,
    cancel_requested: detail.cancel_requested,
    models_with_oos: Number(detail.summary?.models_with_oos ?? item.models_with_oos),
    oos_samples_total: Number(detail.summary?.oos_samples_total ?? detail.progress_current ?? item.oos_samples_total)
  };
}

function ReliabilityChart({
  bins,
  title
}: {
  bins: ReliabilityBin[];
  title: string;
}) {
  const width = 420;
  const height = 260;
  const pad = 36;
  const plotW = width - pad * 2;
  const plotH = height - pad * 2;

  if (!bins.length) {
    return <p className="muted">Nessun dato per la reliability curve.</p>;
  }

  const toX = (p: number) => pad + p * plotW;
  const toY = (p: number) => pad + (1 - p) * plotH;

  const perfect = `M ${toX(0)} ${toY(0)} L ${toX(1)} ${toY(1)}`;
  const points = bins
    .filter((bin) => bin.mean_predicted !== null && bin.mean_actual !== null)
    .map((bin) => `${toX(bin.mean_predicted!)} ${toY(bin.mean_actual!)}`)
    .join(" L ");
  const modelPath = points ? `M ${points}` : "";

  return (
    <div className="card chart-card">
      <h4>{title}</h4>
      <svg
        viewBox={`0 0 ${width} ${height}`}
        role="img"
        aria-label={title}
        className="reliability-chart"
        style={{ width: "100%", maxWidth: width, height: "auto" }}
      >
        <rect x={pad} y={pad} width={plotW} height={plotH} fill="#f8fafc" stroke="#cbd5e1" />
        <path d={perfect} stroke="#94a3b8" strokeDasharray="4 4" fill="none" />
        {modelPath ? <path d={modelPath} stroke="#2563eb" strokeWidth={2} fill="none" /> : null}
        {bins.map((bin) => {
          if (bin.mean_predicted === null || bin.mean_actual === null) return null;
          return (
            <circle
              key={bin.bin_index}
              cx={toX(bin.mean_predicted)}
              cy={toY(bin.mean_actual)}
              r={bin.insufficient_sample ? 3 : 5}
              fill={bin.insufficient_sample ? "#f59e0b" : "#2563eb"}
            />
          );
        })}
        <text x={pad} y={height - 8} fontSize={11} fill="#64748b">
          Probabilità predetta
        </text>
        <text
          x={8}
          y={pad + plotH / 2}
          fontSize={11}
          fill="#64748b"
          transform={`rotate(-90 8 ${pad + plotH / 2})`}
        >
          Frequenza osservata
        </text>
      </svg>
      <p className="muted small">
        Linea tratteggiata = calibrazione perfetta. Punti arancioni = fascia con campione
        insufficiente.
      </p>
    </div>
  );
}

function ReliabilityTable({ bins }: { bins: ReliabilityBin[] }) {
  if (!bins.length) return null;
  return (
    <div className="table-wrap">
      <table className="data-table compact">
        <thead>
          <tr>
            <th>Fascia</th>
            <th>N</th>
            <th>Media predetta</th>
            <th>Media osservata</th>
            <th>Gap</th>
            <th>Campione</th>
          </tr>
        </thead>
        <tbody>
          {bins.map((bin) => (
            <tr key={bin.bin_index} className={bin.insufficient_sample ? "row-warning" : undefined}>
              <td>
                {formatPct(bin.bin_start)} – {formatPct(bin.bin_end)}
              </td>
              <td>{bin.count}</td>
              <td>{formatPct(bin.mean_predicted)}</td>
              <td>{formatPct(bin.mean_actual)}</td>
              <td>{formatPct(bin.calibration_gap)}</td>
              <td>{bin.insufficient_sample ? "Insufficiente" : "OK"}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function CalibrationPage() {
  const [list, setList] = useState<CalibrationRunListItem[]>([]);
  const [run, setRun] = useState<CalibrationRun | null>(null);
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [reloadKey, setReloadKey] = useState(0);
  const [versionFilter, setVersionFilter] = useState<MLModelVersion | "all">("all");
  const [modelFilter, setModelFilter] = useState<string>("all");
  const [methodView, setMethodView] = useState<"raw" | "platt" | "isotonic">("raw");

  useEffect(() => {
    async function load() {
      try {
        setLoading(true);
        const listed = await apiClient.getCalibrationRuns({ limit: 20, offset: 0 });
        setList(listed.items);
        if (listed.items.length === 0) {
          setRun(null);
          setSelectedId(null);
          setError(null);
          return;
        }
        const targetId = selectedId ?? listed.items[0].id;
        const detail = await apiClient.getCalibrationRun(targetId);
        setSelectedId(detail.id);
        setRun(detail);
        setError(null);
      } catch (err) {
        if (err instanceof ApiError && err.status === 404) {
          setRun(null);
          setError(null);
        } else {
          setError(err instanceof Error ? err.message : "Errore inatteso.");
        }
      } finally {
        setLoading(false);
      }
    }
    void load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [reloadKey]);

  useEffect(() => {
    if (selectedId === null || list.length === 0) return;
    if (run?.id === selectedId) return;
    async function loadSelected() {
      try {
        const detail = await apiClient.getCalibrationRun(selectedId!);
        setRun(detail);
        setActionError(null);
      } catch (err) {
        setActionError(err instanceof Error ? err.message : "Errore caricamento run.");
      }
    }
    void loadSelected();
  }, [selectedId, list.length, run?.id]);

  const activeRun = useMemo(
    () => list.find((item) => ACTIVE_RUN_STATUSES.has(item.status)) ?? null,
    [list]
  );
  const activeRunId = activeRun?.id ?? null;
  const progressRun =
    activeRun && run?.id === activeRun.id
      ? run
      : activeRun
        ? {
            status: activeRun.status,
            current_phase: activeRun.current_phase,
            progress_pct: activeRun.progress_pct,
            progress_current: activeRun.progress_current,
            progress_total: activeRun.progress_total
          }
        : null;

  useEffect(() => {
    if (activeRunId === null) return;
    let cancelled = false;
    const poll = async () => {
      try {
        const detail = await apiClient.getCalibrationRun(activeRunId);
        if (cancelled) return;
        if (run?.id === detail.id) {
          setRun(detail);
        }
        setList((items) =>
          items.map((item) =>
            item.id === detail.id ? syncListItemProgress(item, detail) : item
          )
        );
      } catch {
        // keep polling on transient errors while run is active
      }
    };
    void poll();
    const timer = window.setInterval(() => void poll(), RUN_POLL_INTERVAL_MS);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, [activeRunId, run?.id]);

  const filteredResults = useMemo(() => {
    if (!run?.results) return [];
    return run.results.filter((item) => {
      if (versionFilter !== "all" && item.model_version !== versionFilter) return false;
      if (modelFilter !== "all" && item.model_name !== modelFilter) return false;
      return true;
    });
  }, [run, versionFilter, modelFilter]);

  const selectedResult = filteredResults[0];

  const methodBins = useMemo(() => {
    const aggregate = selectedResult?.aggregate as Record<string, MethodMetrics> | undefined;
    return aggregate?.[methodView]?.reliability_bins ?? [];
  }, [selectedResult, methodView]);

  async function handleStart() {
    try {
      setBusy(true);
      setActionError(null);
      const response = await apiClient.startCalibrationRun({ blocking: false });
      setSelectedId(response.run.id);
      setRun(response.run);
      setReloadKey((value) => value + 1);
    } catch (err) {
      setActionError(err instanceof Error ? err.message : "Avvio calibrazione fallito.");
    } finally {
      setBusy(false);
    }
  }

  async function handleCancel() {
    const targetId = run?.id ?? activeRun?.id;
    if (targetId === undefined) return;
    try {
      setActionError(null);
      await apiClient.cancelCalibrationRun(targetId);
      const detail = await apiClient.getCalibrationRun(targetId);
      setRun(detail);
      setList((items) =>
        items.map((item) => (item.id === detail.id ? syncListItemProgress(item, detail) : item))
      );
    } catch (err) {
      setActionError(err instanceof Error ? err.message : "Annullamento calibrazione fallito.");
    }
  }

  if (loading) {
    return <LoadingState title="Caricamento calibrazione..." />;
  }

  if (error) {
    return <ErrorState title="Errore calibrazione" message={error} />;
  }

  return (
    <section className="page">
      <header className="page-header">
        <div>
          <h2>Calibrazione probabilità</h2>
          <p className="muted">
            Analisi su probabilità OOS del walk-forward. Non attiva automaticamente la
            calibrazione sul modello pubblico.
          </p>
        </div>
        <div className="actions inline">
          <button
            type="button"
            className="btn primary"
            disabled={busy || Boolean(activeRun)}
            onClick={() => void handleStart()}
          >
            {busy ? "Avvio..." : "Avvia calibrazione"}
          </button>
        </div>
      </header>

      {progressRun ? (
        <LongRunningJobProgress
          status={progressRun.status}
          currentPhase={progressRun.current_phase}
          progressPct={progressRun.progress_pct}
          progressCurrent={progressRun.progress_current}
          progressTotal={progressRun.progress_total}
          onCancel={() => handleCancel()}
        />
      ) : null}

      {actionError ? <div className="alert error">{actionError}</div> : null}
      {run?.error_message ? <div className="alert error">{run.error_message}</div> : null}

      {list.length === 0 ? (
        <EmptyState
          title="Nessuna run calibrazione"
          message="Avvia la prima analisi per confrontare probabilità grezze, Platt scaling e isotonic regression."
        />
      ) : (
        <>
          <div className="toolbar">
            <label>
              Run
              <select
                value={selectedId ?? ""}
                onChange={(event) => setSelectedId(Number(event.target.value))}
              >
                {list.map((item) => (
                  <option key={item.id} value={item.id}>
                    #{item.id} · {statusLabel(item.status)} · {formatDateTime(item.finished_at)}
                  </option>
                ))}
              </select>
            </label>
            <label>
              Versione
              <select
                value={versionFilter}
                onChange={(event) => setVersionFilter(event.target.value as MLModelVersion | "all")}
              >
                <option value="all">Tutte</option>
                <option value="v1">v1</option>
                <option value="v2">v2</option>
                <option value="v3">v3</option>
              </select>
            </label>
            <label>
              Modello
              <select value={modelFilter} onChange={(event) => setModelFilter(event.target.value)}>
                <option value="all">Tutti</option>
                <option value="logistic_regression">logistic_regression</option>
                <option value="random_forest">random_forest</option>
              </select>
            </label>
            <label>
              Metodo grafico
              <select
                value={methodView}
                onChange={(event) =>
                  setMethodView(event.target.value as "raw" | "platt" | "isotonic")
                }
              >
                <option value="raw">Grezzo</option>
                <option value="platt">Platt</option>
                <option value="isotonic">Isotonic</option>
              </select>
            </label>
          </div>

          {run ? (
            <>
              <div className="metric-grid">
                <MetricCard label="Stato" value={statusLabel(run.status)} />
                <MetricCard label="Campioni OOS" value={String(run.summary?.oos_samples_total ?? "-")} />
                <MetricCard
                  label="ECE grezzo"
                  value={formatNum(metricFromAggregate(selectedResult, "raw", "ece"))}
                />
                <MetricCard
                  label="ECE Platt"
                  value={formatNum(metricFromAggregate(selectedResult, "platt", "ece"))}
                />
                <MetricCard
                  label="ECE isotonic"
                  value={formatNum(metricFromAggregate(selectedResult, "isotonic", "ece"))}
                />
                <MetricCard
                  label="Brier grezzo"
                  value={formatNum(metricFromAggregate(selectedResult, "raw", "brier_score"))}
                />
                <MetricCard
                  label="Log loss grezzo"
                  value={formatNum(metricFromAggregate(selectedResult, "raw", "log_loss"))}
                />
                <MetricCard
                  label="MCE grezzo"
                  value={formatNum(metricFromAggregate(selectedResult, "raw", "mce"))}
                />
              </div>

              {selectedResult ? (
                <>
                  <ReliabilityChart bins={methodBins} title={`Reliability curve (${methodView})`} />
                  <ReliabilityTable bins={methodBins} />

                  <div className="card">
                    <h3>Confronto metodi</h3>
                    <div className="table-wrap">
                      <table className="data-table compact">
                        <thead>
                          <tr>
                            <th>Metodo</th>
                            <th>Brier</th>
                            <th>Log loss</th>
                            <th>ECE</th>
                            <th>MCE</th>
                            <th>Δ Brier vs grezzo</th>
                          </tr>
                        </thead>
                        <tbody>
                          {(["raw", "platt", "isotonic"] as const).map((method) => {
                            const deltas = selectedResult.comparison?.deltas as
                              | Record<string, Record<string, number | null>>
                              | undefined;
                            return (
                              <tr key={method}>
                                <td>{method}</td>
                                <td>{formatNum(metricFromAggregate(selectedResult, method, "brier_score"))}</td>
                                <td>{formatNum(metricFromAggregate(selectedResult, method, "log_loss"))}</td>
                                <td>{formatNum(metricFromAggregate(selectedResult, method, "ece"))}</td>
                                <td>{formatNum(metricFromAggregate(selectedResult, method, "mce"))}</td>
                                <td>
                                  {method === "raw"
                                    ? "-"
                                    : formatNum(deltas?.[method]?.brier_score ?? null)}
                                </td>
                              </tr>
                            );
                          })}
                        </tbody>
                      </table>
                    </div>
                    <p className="muted small">
                      Intervallo OOS: {selectedResult.date_min ?? "-"} → {selectedResult.date_max ?? "-"} ·
                      campioni {selectedResult.oos_samples_total}
                    </p>
                  </div>
                </>
              ) : (
                <EmptyState
                  title="Nessun risultato per i filtri"
                  message="Prova a cambiare versione o modello."
                />
              )}
            </>
          ) : null}
        </>
      )}
    </section>
  );
}
