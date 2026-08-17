import { useCallback, useEffect, useState } from "react";

import { MetricCard } from "../components/MetricCard";
import { EmptyState, ErrorState, LoadingState } from "../components/Status";
import { apiClient, ApiError } from "../services/apiClient";
import type { GlobalUpdateReportRead, GlobalUpdateStatus } from "../types/api";
import { marketLabel, uiVersionOrMarketLabel } from "../utils/markets";

function formatDateTime(value: string | null | undefined) {
  if (!value) return "-";
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return value;
  return parsed.toLocaleString("it-IT", {
    day: "2-digit",
    month: "2-digit",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit"
  });
}

function formatDuration(seconds: number | null | undefined) {
  if (seconds === null || seconds === undefined) return "-";
  if (seconds < 60) {
    return `${seconds.toLocaleString("it-IT", { maximumFractionDigits: 1 })}s`;
  }
  const minutes = Math.floor(seconds / 60);
  const rest = Math.round(seconds % 60);
  return `${minutes}m ${rest}s`;
}

function statusLabel(status: GlobalUpdateStatus | string) {
  switch (status) {
    case "completed":
      return "Completato";
    case "completed_with_errors":
      return "Completato con errori";
    case "failed":
      return "Fallito";
    case "cancelled":
      return "Annullato";
    case "running":
      return "In corso";
    case "pending":
      return "In coda";
    case "skipped":
      return "Saltato";
    default:
      return status;
  }
}

function statusClass(status: string) {
  if (status === "completed") return "won";
  if (status === "failed" || status === "cancelled") return "lost";
  if (status === "completed_with_errors" || status === "skipped") return "pending";
  return "pending";
}

function asText(value: unknown) {
  if (value === null || value === undefined || value === "") return "-";
  return String(value);
}

function phaseDisplayName(phase: string) {
  if (phase === "extra_market_predictions") return "Mercati extra (1° set, O/U)";
  return phase;
}

export function GlobalUpdateReportPage() {
  const [report, setReport] = useState<GlobalUpdateReportRead | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      setLoading(true);
      const latest = await apiClient.getGlobalUpdateLatest();
      if (!latest) {
        setReport(null);
        setError(null);
        return;
      }
      const next = await apiClient.getGlobalUpdateReport(latest.id);
      setReport(next);
      setError(null);
    } catch (err) {
      const message =
        err instanceof ApiError
          ? err.message
          : err instanceof Error
            ? err.message
            : "Errore nel caricamento del report.";
      setError(message);
      setReport(null);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  if (loading) {
    return <LoadingState title="Caricamento report aggiornamento..." />;
  }

  if (error) {
    return <ErrorState title="Report non disponibile" message={error} />;
  }

  if (!report) {
    return (
      <EmptyState
        title="Nessuna run"
        message='Esegui "Aggiorna tutto" nella sidebar per generare il primo report.'
      />
    );
  }

  const summary = report.summary ?? {};
  const completed = Number(summary.combinations_completed ?? 0);
  const failed = Number(summary.combinations_failed ?? 0);
  const skipped = Number(summary.combinations_skipped ?? 0);
  const fixtures = Number(summary.fixtures_processed ?? 0);
  const slips = Number(summary.slips_generated ?? 0);
  const walkForward =
    summary.walk_forward && typeof summary.walk_forward === "object"
      ? (summary.walk_forward as Record<string, unknown>)
      : null;
  const extraMarkets =
    summary.extra_markets && typeof summary.extra_markets === "object"
      ? (summary.extra_markets as Record<string, unknown>)
      : null;
  const extraByMarket =
    extraMarkets?.by_market && typeof extraMarkets.by_market === "object"
      ? (extraMarkets.by_market as Record<string, Record<string, number>>)
      : {};
  const extraMarketsStatus =
    extraMarkets?.available === false || extraMarkets?.error
      ? "failed"
      : extraMarkets
        ? "completed"
        : "skipped";
  const extraMarketRows = Object.entries(extraByMarket).map(([market, counts]) => ({
    market,
    published: Number(counts.published ?? 0),
    skipped: Object.entries(counts)
      .filter(([key]) => key.startsWith("skipped"))
      .reduce((sum, [, value]) => sum + Number(value ?? 0), 0)
  }));

  return (
    <section className="page">
      <header className="page-header">
        <div>
          <h2>Report aggiornamento</h2>
          <p>
            Esito dell&apos;ultima run globale: mercati aggiornati (Match / 1° set / O/U), fasi,
            errori e warning.
          </p>
        </div>
        <div className="header-actions">
          <button type="button" className="action-button secondary" onClick={() => void load()}>
            Ricarica
          </button>
        </div>
      </header>

      <p className="note">
        Gli errori qui sotto sono fallimenti della run (import o generazione mercati). Lo stato{" "}
        <strong>Da generare</strong> in Partite è diverso: indica solo che quella partita non ha
        ancora una previsione salvata (spesso per dati mancanti), non necessariamente un errore di
        aggiornamento.
      </p>

      <div className="panel-header report-run-header">
        <div className="report-run-meta">
          <span className="pill">run #{report.run_id}</span>
          <span className="pill">{report.origin}</span>
          <span className={`slip-status-badge ${statusClass(report.status)}`}>
            {statusLabel(report.status)}
          </span>
          <span className="pill">{report.run_date}</span>
        </div>
        <div className="report-run-times">
          <small>Inizio: {formatDateTime(report.started_at)}</small>
          <small>Fine: {formatDateTime(report.finished_at)}</small>
          <small>Durata: {formatDuration(report.duration_seconds)}</small>
        </div>
      </div>

      <div className="metrics-grid">
        <MetricCard label="Mercati ok" value={completed} />
        <MetricCard label="Mercati falliti" value={failed} />
        <MetricCard label="Mercati saltati" value={skipped} />
        <MetricCard label="Partite processate" value={fixtures} />
        <MetricCard label="Schedine generate" value={slips} />
        <MetricCard label="Errori" value={report.errors.length} />
        <MetricCard label="Warning" value={report.warnings.length} />
      </div>

      {walkForward ? (
        <article className="panel">
          <div className="panel-header">
            <h3>Walk-forward (osservabilità)</h3>
            <span className="pill">
              {walkForward.available ? `run #${String(walkForward.latest_run_id ?? "-")}` : "n/d"}
            </span>
          </div>
          <p className="note">
            Separato dalle metriche live e dal modello pubblico. Dettaglio fold in{" "}
            <strong>Walk-forward</strong> (BACKTEST / OPS).
          </p>
          <div className="metrics-grid">
            <MetricCard label="Stato WF" value={String(walkForward.status ?? "n/d")} />
            <MetricCard label="Modo" value={String(walkForward.mode ?? "-")} />
            <MetricCard
              label="Folds ok"
              value={Number(walkForward.folds_completed ?? 0)}
            />
            <MetricCard
              label="Folds saltati"
              value={Number(walkForward.folds_skipped ?? 0)}
            />
            <MetricCard
              label="Leakage flags"
              value={Number(walkForward.leakage_flags_total ?? 0)}
            />
          </div>
        </article>
      ) : null}

      <article className="panel">
        <div className="panel-header">
          <h3>Errori</h3>
          <span className="pill">{report.errors.length}</span>
        </div>
        {report.errors.length === 0 ? (
          <EmptyState title="Nessun errore" message="L'ultima run non ha registrato errori." />
        ) : (
          <ul className="report-message-list errors">
            {report.errors.map((message, index) => (
              <li key={`error-${index}`}>{message}</li>
            ))}
          </ul>
        )}
      </article>

      {report.warnings.length > 0 ? (
        <article className="panel">
          <div className="panel-header">
            <h3>Warning</h3>
            <span className="pill">{report.warnings.length}</span>
          </div>
          <ul className="report-message-list warnings">
            {report.warnings.map((message, index) => (
              <li key={`warning-${index}`}>{message}</li>
            ))}
          </ul>
        </article>
      ) : null}

      <article className="panel">
        <div className="panel-header">
          <h3>Mercati aggiornati</h3>
          <span className="pill">{report.items.length + (extraMarketRows.length ? 1 : 0)} mercati</span>
        </div>
        {report.items.length === 0 && extraMarketRows.length === 0 ? (
          <EmptyState
            title="Nessun mercato"
            message="La run non ha elaborato mercati (Match / 1° set / O/U)."
          />
        ) : (
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Mercato</th>
                  <th>Stato</th>
                  <th>Previsioni / tip</th>
                  <th>Schedine</th>
                  <th>Durata</th>
                  <th>Dettaglio</th>
                </tr>
              </thead>
              <tbody>
                {report.items.map((item) => (
                  <tr key={`${item.model_version}-${item.model_name}`}>
                    <td>
                      <span className="market-badge market-match_winner">
                        {uiVersionOrMarketLabel(item.model_version)}
                      </span>
                    </td>
                    <td>
                      <span className={`slip-status-badge ${statusClass(item.status)}`}>
                        {statusLabel(item.status)}
                      </span>
                    </td>
                    <td>{item.predictions_generated}</td>
                    <td>{item.slips_generated}</td>
                    <td>{formatDuration(item.duration_seconds)}</td>
                    <td className={item.error_message ? "action-error" : undefined}>
                      {item.error_message ??
                        (item.warnings.length ? item.warnings.join("; ") : "-")}
                    </td>
                  </tr>
                ))}
                {extraMarketRows.map((row) => (
                  <tr key={row.market}>
                    <td>
                      <span className={`market-badge market-${row.market}`}>
                        {marketLabel(row.market)}
                      </span>
                    </td>
                    <td>
                      <span className={`slip-status-badge ${statusClass(extraMarketsStatus)}`}>
                        {statusLabel(extraMarketsStatus)}
                      </span>
                    </td>
                    <td>{row.published}</td>
                    <td>—</td>
                    <td>—</td>
                    <td>
                      pubblicati {row.published}
                      {row.skipped ? ` · saltati ${row.skipped}` : ""}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </article>

      <article className="panel">
        <div className="panel-header">
          <h3>Fasi</h3>
          <span className="pill">{report.phases.length}</span>
        </div>
        {report.phases.length === 0 ? (
          <EmptyState
            title="Nessuna fase dettagliata"
            message="Il report non contiene il dettaglio fasi (run incompleta o report ricostruito)."
          />
        ) : (
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Fase</th>
                  <th>Stato</th>
                  <th>Durata</th>
                  <th>Dettaglio</th>
                </tr>
              </thead>
              <tbody>
                {report.phases.map((phase, index) => {
                  const phaseName = phaseDisplayName(asText(phase.phase ?? `fase-${index + 1}`));
                  const phaseStatus = asText(phase.status);
                  const phaseError = phase.error ? String(phase.error) : null;
                  const extraKeys = Object.entries(phase).filter(
                    ([key]) =>
                      !["phase", "status", "duration_seconds", "error", "extra_markets"].includes(
                        key
                      )
                  );
                  const detailParts = [
                    ...(phaseError ? [`errore: ${phaseError}`] : []),
                    ...extraKeys.map(([key, value]) => `${key}: ${asText(value)}`)
                  ];
                  return (
                    <tr key={`${phaseName}-${index}`}>
                      <td>{phaseName}</td>
                      <td>
                        <span className={`slip-status-badge ${statusClass(phaseStatus)}`}>
                          {statusLabel(phaseStatus)}
                        </span>
                      </td>
                      <td>{formatDuration(phase.duration_seconds)}</td>
                      <td className={phaseError ? "action-error" : undefined}>
                        {detailParts.length ? detailParts.join(" · ") : "-"}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </article>
    </section>
  );
}
