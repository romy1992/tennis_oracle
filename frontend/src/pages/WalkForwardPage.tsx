import { useEffect, useMemo, useState } from "react";

import { MetricCard } from "../components/MetricCard";
import {
  LongRunningJobProgress
} from "../components/LongRunningJobProgress";
import { EmptyState, ErrorState, LoadingState } from "../components/Status";
import { apiClient, ApiError } from "../services/apiClient";
import type {
  MLModelVersion,
  WalkForwardFold,
  WalkForwardOfficialBenchmarkMetrics,
  WalkForwardMode,
  WalkForwardRun,
  WalkForwardRunListItem
} from "../types/api";

function formatPct(value: number | null | undefined) {
  if (value === null || value === undefined) return "-";
  return `${(value * 100).toLocaleString("it-IT", { maximumFractionDigits: 1 })}%`;
}

function formatNum(value: number | null | undefined, digits = 3) {
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
    case "skipped_insufficient_data":
      return "Saltato (dati insufficienti)";
    case "skipped_single_class":
      return "Saltato (classe singola)";
    case "error":
      return "Errore fold";
    default:
      return status;
  }
}

function metricFromFold(fold: WalkForwardFold, key: string): number | null {
  const metrics = fold.metrics;
  if (!metrics || typeof metrics !== "object") return null;
  const value = (metrics as Record<string, unknown>)[key];
  return typeof value === "number" ? value : null;
}

function officialMetricsFromFold(
  fold: WalkForwardFold
): WalkForwardOfficialBenchmarkMetrics | null {
  const metrics = fold.metrics;
  if (!metrics || typeof metrics !== "object") return null;
  const nested = (metrics as Record<string, unknown>).official_benchmark;
  if (!nested || typeof nested !== "object") return null;
  return nested as WalkForwardOfficialBenchmarkMetrics;
}

function metricFromOfficial(fold: WalkForwardFold, key: keyof WalkForwardOfficialBenchmarkMetrics) {
  const metrics = officialMetricsFromFold(fold);
  if (!metrics) return null;
  const value = metrics[key];
  return typeof value === "number" ? value : null;
}

function sampleMetaFromFold(fold: WalkForwardFold): Record<string, unknown> | null {
  const coverage = fold.coverage;
  if (!coverage || typeof coverage !== "object") return null;
  const sample = (coverage as Record<string, unknown>).official_benchmark_sample;
  if (!sample || typeof sample !== "object") return null;
  return sample as Record<string, unknown>;
}

function hasSampleMismatch(fold: WalkForwardFold): boolean {
  return Boolean(sampleMetaFromFold(fold)?.sample_mismatch_detected);
}

function sampleMismatchTitle(fold: WalkForwardFold): string {
  const sample = sampleMetaFromFold(fold);
  if (!sample || !sample.sample_mismatch_detected) return "Campione allineato";
  return [
    "Confronto su campione comune",
    `rows_total_test: ${String(sample.rows_total_test ?? "-")}`,
    `rows_common_official: ${String(sample.rows_common_official ?? "-")}`,
    `rows_excluded_for_common_sample: ${String(sample.rows_excluded_for_common_sample ?? "-")}`,
    `missing_rows_by_contender: ${JSON.stringify(sample.missing_rows_by_contender ?? {})}`
  ].join("\n");
}

const CONTENDER_OPTIONS = [
  "market_favorite",
  "market_no_vig",
  "atp_ranking",
  "elo",
  "logistic_regression",
  "random_forest"
] as const;
const PAGE_VERSION_OPTIONS: MLModelVersion[] = ["v1", "v2", "v3"];

type ContenderFilter = (typeof CONTENDER_OPTIONS)[number] | "all";

const ACTIVE_RUN_STATUSES = new Set(["pending", "running"]);
const RUN_POLL_INTERVAL_MS = 12_000;

function syncListItemProgress(
  item: WalkForwardRunListItem,
  detail: WalkForwardRun
): WalkForwardRunListItem {
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
    folds_completed: Number(detail.summary?.folds_completed ?? detail.progress_current ?? item.folds_completed)
  };
}

export function WalkForwardPage() {
  const [list, setList] = useState<WalkForwardRunListItem[]>([]);
  const [run, setRun] = useState<WalkForwardRun | null>(null);
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [reloadKey, setReloadKey] = useState(0);
  const [mode, setMode] = useState<WalkForwardMode>("expanding");
  const [versionFilter, setVersionFilter] = useState<MLModelVersion | "all">("all");
  const [contenderFilter, setContenderFilter] = useState<ContenderFilter>("all");
  const [versionPageIndex, setVersionPageIndex] = useState(0);
  const [dayPageIndex, setDayPageIndex] = useState(0);

  useEffect(() => {
    async function load() {
      try {
        setLoading(true);
        const listed = await apiClient.getWalkForwardRuns({ limit: 20, offset: 0 });
        setList(listed.items);
        if (listed.items.length === 0) {
          setRun(null);
          setSelectedId(null);
          setError(null);
          return;
        }
        const targetId = selectedId ?? listed.items[0].id;
        const detail = await apiClient.getWalkForwardRun(targetId);
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
    // selectedId intentionally omitted: initial load + reloadKey; selection handled below
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [reloadKey]);

  useEffect(() => {
    if (selectedId === null || list.length === 0) return;
    if (run?.id === selectedId) return;
    async function loadSelected() {
      try {
        const detail = await apiClient.getWalkForwardRun(selectedId!);
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
        const detail = await apiClient.getWalkForwardRun(activeRunId);
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

  const folds = useMemo(() => {
    const items = run?.folds ?? [];
    return items.filter((fold) => {
      if (versionFilter !== "all" && fold.model_version !== versionFilter) return false;
      if (contenderFilter !== "all" && fold.model_name !== contenderFilter) return false;
      return true;
    });
  }, [run, versionFilter, contenderFilter]);

  const versionsInScope = useMemo(() => {
    const present = new Set(folds.map((fold) => fold.model_version));
    return PAGE_VERSION_OPTIONS.filter((version) => present.has(version));
  }, [folds]);

  useEffect(() => {
    if (versionPageIndex >= versionsInScope.length) {
      setVersionPageIndex(0);
    }
  }, [versionPageIndex, versionsInScope.length]);

  const pagedVersion = versionsInScope[versionPageIndex] ?? null;

  const foldsByVersion = useMemo(() => {
    if (!pagedVersion) return [];
    return folds.filter((fold) => fold.model_version === pagedVersion);
  }, [folds, pagedVersion]);

  const testDaysInScope = useMemo(() => {
    return Array.from(new Set(foldsByVersion.map((fold) => fold.test_start))).sort();
  }, [foldsByVersion]);

  useEffect(() => {
    if (dayPageIndex >= testDaysInScope.length) {
      setDayPageIndex(0);
    }
  }, [dayPageIndex, testDaysInScope.length]);

  const pagedTestDay = testDaysInScope[dayPageIndex] ?? null;

  const tableFolds = useMemo(() => {
    if (!pagedVersion || !pagedTestDay) return [];
    return foldsByVersion.filter((fold) => fold.test_start === pagedTestDay);
  }, [foldsByVersion, pagedVersion, pagedTestDay]);

  const skipped = tableFolds.filter((fold) => String(fold.status).startsWith("skipped"));
  const leakage = tableFolds.filter((fold) => (fold.leakage_flags ?? []).length > 0);
  const completed = tableFolds.filter((fold) => fold.status === "completed");
  const sampleMismatchFolds = tableFolds.filter((fold) => hasSampleMismatch(fold));

  const officialContenders = useMemo(() => {
    const raw = run?.summary?.official_contenders;
    if (!Array.isArray(raw)) return [];
    return raw.filter((item): item is string => typeof item === "string");
  }, [run]);

  const officialMismatchCount = Number(run?.summary?.official_sample_mismatch_folds ?? 0);

  async function handleStart() {
    try {
      setBusy(true);
      setActionError(null);
      const response = await apiClient.startWalkForwardRun({
        mode,
        blocking: false
      });
      setSelectedId(response.run.id);
      setReloadKey((value) => value + 1);
    } catch (err) {
      setActionError(err instanceof Error ? err.message : "Avvio walk-forward fallito.");
    } finally {
      setBusy(false);
    }
  }

  async function handleCancel() {
    const targetId = run?.id ?? activeRun?.id;
    if (targetId === undefined) return;
    try {
      setActionError(null);
      await apiClient.cancelWalkForwardRun(targetId);
      const detail = await apiClient.getWalkForwardRun(targetId);
      setRun(detail);
      setList((items) =>
        items.map((item) => (item.id === detail.id ? syncListItemProgress(item, detail) : item))
      );
    } catch (err) {
      setActionError(err instanceof Error ? err.message : "Annullamento walk-forward fallito.");
    }
  }

  if (loading) {
    return <LoadingState title="Caricamento walk-forward..." />;
  }

  if (error) {
    return <ErrorState title="Walk-forward non disponibile" message={error} />;
  }

  return (
    <section className="page">
      <header className="page-header">
        <div>
          <h2>Validazione walk-forward</h2>
          <p>
            Validazione temporale multi-fold (expanding/rolling). Non aggiorna il modello
            pubblico e non mescola i risultati con le metriche live.
          </p>
        </div>
        <div className="page-actions">
          <label>
            Modalità
            <select
              value={mode}
              onChange={(event) => setMode(event.target.value as WalkForwardMode)}
              disabled={busy}
            >
              <option value="expanding">Expanding</option>
              <option value="rolling">Rolling</option>
            </select>
          </label>
          <button
            type="button"
            className="action-button"
            disabled={busy || Boolean(activeRun)}
            onClick={() => void handleStart()}
          >
            {busy ? "Avvio..." : "Avvia walk-forward"}
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

      {actionError ? <p className="inline-error">{actionError}</p> : null}

      {list.length === 0 ? (
        <EmptyState
          title="Nessuna run walk-forward"
          message="Avvia una validazione manuale oppure usa il job CLI run_walk_forward."
        />
      ) : (
        <>
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>ID</th>
                  <th>Stato</th>
                  <th>Modo</th>
                  <th>Versioni</th>
                  <th>Completati</th>
                  <th>Saltati</th>
                  <th>Leakage</th>
                  <th>Fine</th>
                </tr>
              </thead>
              <tbody>
                {list.map((item) => (
                  <tr
                    key={item.id}
                    className={item.id === selectedId ? "row-selected" : undefined}
                    onClick={() => setSelectedId(item.id)}
                    style={{ cursor: "pointer" }}
                  >
                    <td>{item.id}</td>
                    <td>{statusLabel(item.status)}</td>
                    <td>{item.mode}</td>
                    <td>{item.versions_requested}</td>
                    <td>{item.folds_completed}</td>
                    <td>{item.folds_skipped}</td>
                    <td>{item.leakage_flags_total}</td>
                    <td>{formatDateTime(item.finished_at)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          {run ? (
            <>
              {run.status === "failed" || run.error_message ? (
                <article className="panel" style={{ marginBottom: "1rem" }}>
                  <div className="panel-header">
                    <h3>Errore run</h3>
                    <span className="pill">{statusLabel(run.status)}</span>
                  </div>
                  <p className="inline-error" role="alert">
                    {run.error_message ||
                      "La run è fallita senza dettaglio. Controlla i log API (dataset CSV mancanti in Docker: monta PROCESSED_HOST_PATH)."}
                  </p>
                </article>
              ) : null}

              <div className="metric-grid">
                <MetricCard label="Stato run" value={statusLabel(run.status)} />
                <MetricCard
                  label="Folds completati"
                  value={String(completed.length)}
                  hint={`su ${tableFolds.length} nella pagina`}
                />
                <MetricCard
                  label="Folds saltati"
                  value={String(skipped.length)}
                  hint="Dati insufficienti / classe singola"
                />
                <MetricCard
                  label="Leakage flags"
                  value={String(leakage.length)}
                  hint="Possibili segnali da investigare"
                />
                <MetricCard
                  label="Mismatch campione ufficiale"
                  value={String(officialMismatchCount)}
                  hint="Fold con sample_mismatch_detected"
                />
                <MetricCard
                  label="Contender ufficiali"
                  value={officialContenders.length ? officialContenders.join(", ") : "-"}
                />
              </div>

              <div className="page-actions" style={{ marginTop: "1rem" }}>
                <label>
                  Versione
                  <select
                    value={versionFilter}
                    onChange={(event) =>
                      setVersionFilter(event.target.value as MLModelVersion | "all")
                    }
                  >
                    <option value="all">Tutte</option>
                    <option value="v1">v1</option>
                    <option value="v2">v2</option>
                    <option value="v3">v3</option>
                  </select>
                </label>
                <label>
                  Contender
                  <select
                    value={contenderFilter}
                    onChange={(event) => setContenderFilter(event.target.value as ContenderFilter)}
                  >
                    <option value="all">Tutti</option>
                    {CONTENDER_OPTIONS.map((contender) => (
                      <option key={contender} value={contender}>
                        {contender}
                      </option>
                    ))}
                  </select>
                </label>
              </div>

              <div className="page-actions" style={{ marginTop: "0.75rem" }}>
                <div>
                  <strong>Pagina versione:</strong>{" "}
                  {pagedVersion ? `${versionPageIndex + 1}/${versionsInScope.length} (${pagedVersion})` : "-"}
                </div>
                <label>
                  Vai a versione
                  <select
                    value={pagedVersion ?? ""}
                    onChange={(event) => {
                      const target = event.target.value as MLModelVersion;
                      const idx = versionsInScope.findIndex((version) => version === target);
                      if (idx >= 0) {
                        setVersionPageIndex(idx);
                        setDayPageIndex(0);
                      }
                    }}
                    disabled={versionsInScope.length === 0}
                  >
                    {versionsInScope.length === 0 ? <option value="">-</option> : null}
                    {versionsInScope.map((version) => (
                      <option key={version} value={version}>
                        {version}
                      </option>
                    ))}
                  </select>
                </label>
                <button
                  type="button"
                  className="action-button secondary"
                  disabled={versionPageIndex <= 0}
                  onClick={() => {
                    setVersionPageIndex((value) => Math.max(0, value - 1));
                    setDayPageIndex(0);
                  }}
                >
                  Versione precedente
                </button>
                <button
                  type="button"
                  className="action-button secondary"
                  disabled={versionPageIndex >= versionsInScope.length - 1}
                  onClick={() => {
                    setVersionPageIndex((value) =>
                      Math.min(Math.max(versionsInScope.length - 1, 0), value + 1)
                    );
                    setDayPageIndex(0);
                  }}
                >
                  Versione successiva
                </button>
                <div>
                  <strong>Pagina giorno test:</strong>{" "}
                  {pagedTestDay ? `${dayPageIndex + 1}/${testDaysInScope.length} (${pagedTestDay})` : "-"}
                </div>
                <label>
                  Vai a giorno test
                  <select
                    value={pagedTestDay ?? ""}
                    onChange={(event) => {
                      const idx = testDaysInScope.findIndex((day) => day === event.target.value);
                      if (idx >= 0) {
                        setDayPageIndex(idx);
                      }
                    }}
                    disabled={testDaysInScope.length === 0}
                  >
                    {testDaysInScope.length === 0 ? <option value="">-</option> : null}
                    {testDaysInScope.map((day) => (
                      <option key={day} value={day}>
                        {day}
                      </option>
                    ))}
                  </select>
                </label>
                <button
                  type="button"
                  className="action-button secondary"
                  disabled={dayPageIndex <= 0}
                  onClick={() => setDayPageIndex((value) => Math.max(0, value - 1))}
                >
                  Giorno precedente
                </button>
                <button
                  type="button"
                  className="action-button secondary"
                  disabled={dayPageIndex >= testDaysInScope.length - 1}
                  onClick={() =>
                    setDayPageIndex((value) =>
                      Math.min(Math.max(testDaysInScope.length - 1, 0), value + 1)
                    )
                  }
                >
                  Giorno successivo
                </button>
              </div>

              {sampleMismatchFolds.length > 0 ? (
                <p className="inline-error" style={{ marginTop: "0.5rem" }}>
                  Confronto ufficiale calcolato su campione comune: alcune righe sono escluse per
                  evitare confronti tra campioni differenti.
                </p>
              ) : null}

              {run.error_message && run.status !== "failed" ? (
                <p className="inline-error">Errore run: {run.error_message}</p>
              ) : null}

              <div className="table-wrap" style={{ marginTop: "1rem" }}>
                <table>
                  <thead>
                    <tr>
                      <th>Fold</th>
                      <th>Versione</th>
                      <th>Modello</th>
                      <th>Stato</th>
                      <th>Train</th>
                      <th>Test</th>
                      <th>Righe</th>
                      <th>Accuracy</th>
                      <th>Log Loss</th>
                      <th>Brier</th>
                      <th>ROI</th>
                      <th>Yield</th>
                      <th>Drawdown</th>
                      <th>CLV</th>
                      <th>Sample mismatch</th>
                      <th>Leakage</th>
                      <th>Note</th>
                    </tr>
                  </thead>
                  <tbody>
                    {tableFolds.map((fold) => (
                      <tr
                        key={`${fold.id}-${fold.model_version}-${fold.model_name}`}
                        className={
                          String(fold.status).startsWith("skipped")
                            ? "row-warning"
                            : hasSampleMismatch(fold) || (fold.leakage_flags ?? []).length > 0
                              ? "row-warning"
                              : undefined
                        }
                      >
                        <td>{fold.fold_index}</td>
                        <td>{fold.model_version}</td>
                        <td>{fold.model_name}</td>
                        <td>{statusLabel(fold.status)}</td>
                        <td>
                          {fold.train_start} → {fold.train_end}
                        </td>
                        <td>
                          {fold.test_start} → {fold.test_end}
                        </td>
                        <td>
                          {fold.train_rows} / {fold.test_rows}
                        </td>
                        <td>
                          {formatPct(
                            metricFromOfficial(fold, "accuracy") ?? metricFromFold(fold, "accuracy")
                          )}
                        </td>
                        <td>
                          {formatNum(
                            metricFromOfficial(fold, "log_loss") ?? metricFromFold(fold, "log_loss")
                          )}
                        </td>
                        <td>{formatNum(metricFromOfficial(fold, "brier_score"))}</td>
                        <td>{formatPct(metricFromOfficial(fold, "roi"))}</td>
                        <td>{formatPct(metricFromOfficial(fold, "yield"))}</td>
                        <td>{formatNum(metricFromOfficial(fold, "max_drawdown"))}</td>
                        <td>{formatPct(metricFromOfficial(fold, "clv_pct"))}</td>
                        <td title={sampleMismatchTitle(fold)}>
                          {hasSampleMismatch(fold) ? (
                            <span className="pill warning">Warning</span>
                          ) : (
                            <span className="pill">OK</span>
                          )}
                        </td>
                        <td>
                          {(fold.leakage_flags ?? []).length > 0
                            ? fold.leakage_flags.join(", ")
                            : "-"}
                        </td>
                        <td>{fold.skip_reason ?? "-"}</td>
                      </tr>
                    ))}
                    {tableFolds.length === 0 ? (
                      <tr>
                        <td colSpan={15}>Nessun fold per la pagina corrente.</td>
                      </tr>
                    ) : null}
                  </tbody>
                </table>
              </div>

              {Array.isArray(run.summary?.versions_detail) ? (
                <section style={{ marginTop: "1.5rem" }}>
                  <h3>Aggregato benchmark ufficiali</h3>
                  <div className="table-wrap">
                    <table>
                      <thead>
                        <tr>
                          <th>Versione</th>
                          <th>Contender</th>
                          <th>Accuracy</th>
                          <th>Log Loss</th>
                          <th>Brier</th>
                          <th>ROI</th>
                          <th>Yield</th>
                          <th>Drawdown</th>
                          <th>CLV</th>
                        </tr>
                      </thead>
                      <tbody>
                        {run.summary.versions_detail.flatMap((detail, idx) => {
                          const detailRecord = detail as Record<string, unknown>;
                          const version = String(detailRecord.model_version ?? "-");
                          const aggregate = detailRecord.aggregate_metrics as Record<string, unknown> | undefined;
                          const official = aggregate?.official_benchmarks as Record<string, Record<string, unknown>> | undefined;
                          if (!official) {
                            return [
                              <tr key={`${idx}-${version}-empty`}>
                                <td>{version}</td>
                                <td colSpan={8}>Nessun aggregato ufficiale disponibile</td>
                              </tr>
                            ];
                          }
                          return Object.entries(official).map(([name, payload]) => {
                            const acc = (payload.accuracy as Record<string, unknown> | undefined)?.mean;
                            const logLoss = (payload.log_loss as Record<string, unknown> | undefined)?.mean;
                            const brier = (payload.brier_score as Record<string, unknown> | undefined)?.mean;
                            const roi = (payload.roi as Record<string, unknown> | undefined)?.mean;
                            const yld = (payload.yield as Record<string, unknown> | undefined)?.mean;
                            const drawdown = (payload.max_drawdown as Record<string, unknown> | undefined)?.mean;
                            const clv = (payload.clv_pct as Record<string, unknown> | undefined)?.mean;
                            return (
                              <tr key={`${idx}-${version}-${name}`}>
                                <td>{version}</td>
                                <td>{name}</td>
                                <td>{formatPct(typeof acc === "number" ? acc : null)}</td>
                                <td>{formatNum(typeof logLoss === "number" ? logLoss : null)}</td>
                                <td>{formatNum(typeof brier === "number" ? brier : null)}</td>
                                <td>{formatPct(typeof roi === "number" ? roi : null)}</td>
                                <td>{formatPct(typeof yld === "number" ? yld : null)}</td>
                                <td>{formatNum(typeof drawdown === "number" ? drawdown : null)}</td>
                                <td>{formatPct(typeof clv === "number" ? clv : null)}</td>
                              </tr>
                            );
                          });
                        })}
                      </tbody>
                    </table>
                  </div>
                </section>
              ) : null}

              {run.summary?.versions_detail ? (
                <section style={{ marginTop: "1.5rem" }}>
                  <h3>Confronto con holdout attuale</h3>
                  <p>
                    I risultati walk-forward sono affiancati alle metriche holdout già presenti
                    su disco; queste ultime non vengono sovrascritte.
                  </p>
                  <pre className="code-block">
                    {JSON.stringify(run.summary.versions_detail, null, 2)}
                  </pre>
                </section>
              ) : null}
            </>
          ) : null}
        </>
      )}
    </section>
  );
}
