import { useEffect, useMemo, useState } from "react";

import { MetricCard } from "../components/MetricCard";
import { EmptyState, ErrorState, LoadingState } from "../components/Status";
import { apiClient, ApiError } from "../services/apiClient";
import type {
  MLModelVersion,
  WalkForwardFold,
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

const ACTIVE_RUN_STATUSES = new Set(["pending", "running"]);
const RUN_POLL_INTERVAL_MS = 12_000;

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
  const [modelFilter, setModelFilter] = useState<string>("all");

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

  useEffect(() => {
    if (!run || !ACTIVE_RUN_STATUSES.has(run.status)) return;
    let cancelled = false;
    const poll = async () => {
      try {
        const detail = await apiClient.getWalkForwardRun(run.id);
        if (cancelled) return;
        setRun(detail);
        setList((items) =>
          items.map((item) =>
            item.id === detail.id
              ? {
                  ...item,
                  status: detail.status,
                  finished_at: detail.finished_at,
                  duration_seconds: detail.duration_seconds
                }
              : item
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
  }, [run?.id, run?.status]);

  const folds = useMemo(() => {
    const items = run?.folds ?? [];
    return items.filter((fold) => {
      if (versionFilter !== "all" && fold.model_version !== versionFilter) return false;
      if (modelFilter !== "all" && fold.model_name !== modelFilter) return false;
      return true;
    });
  }, [run, versionFilter, modelFilter]);

  const skipped = folds.filter((fold) => String(fold.status).startsWith("skipped"));
  const leakage = folds.filter((fold) => (fold.leakage_flags ?? []).length > 0);
  const completed = folds.filter((fold) => fold.status === "completed");

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
            disabled={busy}
            onClick={() => void handleStart()}
          >
            {busy ? "Avvio..." : "Avvia walk-forward"}
          </button>
        </div>
      </header>

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
                  hint={`su ${folds.length} filtrati`}
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
                  Modello
                  <select
                    value={modelFilter}
                    onChange={(event) => setModelFilter(event.target.value)}
                  >
                    <option value="all">Tutti</option>
                    <option value="logistic_regression">logistic_regression</option>
                    <option value="random_forest">random_forest</option>
                  </select>
                </label>
              </div>

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
                      <th>ROC AUC</th>
                      <th>Leakage</th>
                      <th>Note</th>
                    </tr>
                  </thead>
                  <tbody>
                    {folds.map((fold) => (
                      <tr
                        key={`${fold.id}-${fold.model_version}-${fold.model_name}`}
                        className={
                          String(fold.status).startsWith("skipped")
                            ? "row-warning"
                            : (fold.leakage_flags ?? []).length > 0
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
                        <td>{formatPct(metricFromFold(fold, "accuracy"))}</td>
                        <td>{formatNum(metricFromFold(fold, "roc_auc"))}</td>
                        <td>
                          {(fold.leakage_flags ?? []).length > 0
                            ? fold.leakage_flags.join(", ")
                            : "-"}
                        </td>
                        <td>{fold.skip_reason ?? "-"}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>

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
