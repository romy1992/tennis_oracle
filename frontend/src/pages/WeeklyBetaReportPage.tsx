import { useEffect, useState } from "react";

import { MetricCard } from "../components/MetricCard";
import { EmptyState, ErrorState, LoadingState } from "../components/Status";
import { apiClient, ApiError } from "../services/apiClient";
import type {
  WeeklyBetaMetricDelta,
  WeeklyBetaReport,
  WeeklyBetaReportListItem
} from "../types/api";
import { marketLabel } from "../utils/markets";

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

function formatDelta(delta: WeeklyBetaMetricDelta | undefined, { pct = false } = {}) {
  if (!delta || delta.delta === null || delta.delta === undefined) return "vs prec.: n/d";
  const sign = delta.delta > 0 ? "+" : "";
  if (pct) {
    return `vs prec.: ${sign}${formatNum(delta.delta, 2)} pp`;
  }
  if (Number.isInteger(delta.current) && Number.isInteger(delta.previous)) {
    return `vs prec.: ${sign}${delta.delta}`;
  }
  return `vs prec.: ${sign}${formatNum(delta.delta, 2)}`;
}

function formatDateTime(value: string | null | undefined) {
  if (!value) return "-";
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return value;
  return parsed.toLocaleString("it-IT");
}

function telegramStatusLabel(status: string) {
  switch (status) {
    case "sent":
      return "Inviato";
    case "skipped":
      return "Saltato";
    case "failed":
      return "Fallito";
    default:
      return "In attesa";
  }
}

export function WeeklyBetaReportPage() {
  const [list, setList] = useState<WeeklyBetaReportListItem[]>([]);
  const [report, setReport] = useState<WeeklyBetaReport | null>(null);
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [reloadKey, setReloadKey] = useState(0);

  useEffect(() => {
    async function load() {
      try {
        setLoading(true);
        const listed = await apiClient.getWeeklyBetaReports({ limit: 20, offset: 0 });
        setList(listed.items);
        if (listed.items.length === 0) {
          setReport(null);
          setSelectedId(null);
          setError(null);
          return;
        }
        const targetId = selectedId ?? listed.items[0].id;
        const detail = await apiClient.getWeeklyBetaReport(targetId);
        setSelectedId(detail.id);
        setReport(detail);
        setError(null);
      } catch (err) {
        if (err instanceof ApiError && err.status === 404) {
          setReport(null);
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
    if (selectedId == null || loading) return;
    if (report?.id === selectedId) return;
    async function loadDetail() {
      try {
        const detail = await apiClient.getWeeklyBetaReport(selectedId!);
        setReport(detail);
        setActionError(null);
      } catch (err) {
        setActionError(err instanceof Error ? err.message : "Errore nel dettaglio.");
      }
    }
    void loadDetail();
  }, [selectedId, loading, report?.id]);

  async function handleGenerate(force: boolean) {
    try {
      setBusy(true);
      setActionError(null);
      const result = await apiClient.generateWeeklyBetaReport({
        send_telegram: true,
        force
      });
      setSelectedId(result.report.id);
      setReport(result.report);
      setReloadKey((k) => k + 1);
    } catch (err) {
      setActionError(err instanceof Error ? err.message : "Generazione fallita.");
    } finally {
      setBusy(false);
    }
  }

  if (loading && !report && list.length === 0) {
    return <LoadingState title="Caricamento report settimanale…" />;
  }

  if (error && !report) {
    return <ErrorState title="Report settimanale beta" message={error} />;
  }

  const cur = report?.payload.current;
  const wow = report?.payload.wow;
  const prev = report?.payload.previous;

  return (
    <section className="page">
      <header className="page-header">
        <div>
          <h2>Report settimanale beta</h2>
          <p>
            Snapshot KPI della settimana ISO (lun–dom): utenti, retention, comandi, tip live,
            pipeline, notifiche e feedback, con confronto rispetto alla settimana precedente.
          </p>
        </div>
        <div className="page-header-actions">
          <button
            type="button"
            className="action-button primary"
            disabled={busy}
            onClick={() => void handleGenerate(false)}
          >
            Genera ultima settimana
          </button>
          <button
            type="button"
            className="action-button secondary"
            disabled={busy}
            onClick={() => void handleGenerate(true)}
          >
            Rigenera (force)
          </button>
        </div>
      </header>

      {actionError ? <ErrorState title="Operazione" message={actionError} /> : null}

      {list.length === 0 ? (
        <EmptyState
          title="Nessun report ancora"
          message="Genera il report della settimana precedente o attendi il job pianificato del lunedì."
        />
      ) : (
        <article className="panel">
          <div className="panel-header">
            <h3>Storico report</h3>
            <span className="pill">{list.length}</span>
          </div>
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Settimana</th>
                  <th>Periodo</th>
                  <th>Utenti attivi</th>
                  <th>Tip</th>
                  <th>ROI</th>
                  <th>Telegram</th>
                  <th></th>
                </tr>
              </thead>
              <tbody>
                {list.map((item) => (
                  <tr key={item.id}>
                    <td>{item.week_label}</td>
                    <td>
                      {item.week_start} → {item.week_end}
                    </td>
                    <td>{item.active_users}</td>
                    <td>{item.predictions_published}</td>
                    <td>{formatPct(item.roi_pct)}</td>
                    <td>{telegramStatusLabel(String(item.telegram_status))}</td>
                    <td>
                      <button
                        type="button"
                        className={
                          item.id === selectedId
                            ? "action-button primary"
                            : "action-button secondary"
                        }
                        onClick={() => setSelectedId(item.id)}
                      >
                        Apri
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </article>
      )}

      {report && cur && wow && prev ? (
        <>
          <article className="panel mode-panel mode-panel-live">
            <div className="panel-header">
              <h3>
                {cur.week_label}: {cur.week_start} → {cur.week_end}
              </h3>
              <span className="pill">
                Telegram: {telegramStatusLabel(String(report.telegram_status))}
              </span>
            </div>
            <p>
              Generato {formatDateTime(report.generated_at)} · origine {report.generated_by}
              {report.telegram_sent_at
                ? ` · inviato ${formatDateTime(report.telegram_sent_at)}`
                : ""}
              {report.telegram_error ? ` · ${report.telegram_error}` : ""}
            </p>
            <div className="metrics-grid">
              <MetricCard
                label="Utenti totali"
                value={String(cur.users.total_users)}
                hint={formatDelta(wow.total_users)}
              />
              <MetricCard
                label="Utenti attivi"
                value={String(cur.users.active_users)}
                hint={formatDelta(wow.active_users)}
              />
              <MetricCard
                label="Nuovi utenti"
                value={String(cur.users.new_users)}
                hint={formatDelta(wow.new_users)}
              />
              <MetricCard
                label="Retention W1"
                value={formatPct(cur.users.retention_pct)}
                hint={`coorte ${cur.users.retention_cohort} · ${formatDelta(wow.retention_pct, { pct: true })}`}
              />
            </div>
          </article>

          <article className="panel">
            <div className="panel-header">
              <h3>Utilizzo comandi</h3>
            </div>
            <div className="metrics-grid">
              <MetricCard
                label="Eventi"
                value={String(cur.command_usage.total_events)}
                hint={formatDelta(wow.total_events)}
              />
              <MetricCard
                label="Utenti unici bot"
                value={String(cur.command_usage.unique_users)}
              />
            </div>
            {cur.command_usage.by_action.length === 0 ? (
              <EmptyState title="Nessun comando" message="Nessun evento bot nella settimana." />
            ) : (
              <div className="table-wrap">
                <table>
                  <thead>
                    <tr>
                      <th>Azione</th>
                      <th>Conteggio</th>
                    </tr>
                  </thead>
                  <tbody>
                    {cur.command_usage.by_action.map((row) => (
                      <tr key={row.action}>
                        <td>{row.action}</td>
                        <td>{row.count}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </article>

          <article className="panel">
            <div className="panel-header">
              <h3>Pronostici live · {marketLabel(cur.live_tips.market ?? "match_winner")}</h3>
              <span className="pill">headline = match winner (KPI non misti)</span>
            </div>
            <div className="metrics-grid">
              <MetricCard
                label="Pubblicati"
                value={String(cur.live_tips.predictions_published)}
                hint={formatDelta(wow.predictions_published)}
              />
              <MetricCard label="ROI" value={formatPct(cur.live_tips.roi_pct)} hint={formatDelta(wow.roi_pct, { pct: true })} />
              <MetricCard
                label="Yield"
                value={formatPct(cur.live_tips.yield_pct)}
                hint={formatDelta(wow.yield_pct, { pct: true })}
              />
              <MetricCard
                label="Max drawdown"
                value={formatNum(cur.live_tips.max_drawdown)}
                hint={formatDelta(wow.max_drawdown)}
              />
              <MetricCard label="Hit rate" value={formatPct(cur.live_tips.hit_rate_pct)} />
              <MetricCard label="Profitto" value={formatNum(cur.live_tips.profit)} />
            </div>
            {(cur.live_tips.by_market?.length ?? 0) > 0 ? (
              <div className="table-wrap" style={{ marginTop: "1rem" }}>
                <table>
                  <thead>
                    <tr>
                      <th>Mercato</th>
                      <th>Pubblicati</th>
                      <th>Chiusi</th>
                      <th>Hit rate</th>
                      <th>ROI</th>
                      <th>Profitto</th>
                    </tr>
                  </thead>
                  <tbody>
                    {cur.live_tips.by_market?.map((row) => (
                      <tr key={row.market ?? "market"}>
                        <td>
                          <span className={`market-badge market-${row.market ?? "match_winner"}`}>
                            {marketLabel(row.market)}
                          </span>
                        </td>
                        <td>{row.predictions_published}</td>
                        <td>{row.closed}</td>
                        <td>{formatPct(row.hit_rate_pct)}</td>
                        <td>{formatPct(row.roi_pct)}</td>
                        <td>{formatNum(row.profit)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ) : null}
          </article>

          <article className="panel">
            <div className="panel-header">
              <h3>Pipeline, notifiche, feedback</h3>
            </div>
            <div className="metrics-grid">
              <MetricCard
                label="Run pipeline"
                value={String(cur.pipeline.runs_total)}
                hint={formatDelta(wow.pipeline_errors)}
              />
              <MetricCard
                label="Run falliti / con errori"
                value={`${cur.pipeline.runs_failed} / ${cur.pipeline.runs_completed_with_errors}`}
              />
              <MetricCard
                label="Notifiche fallite"
                value={String(cur.notifications.failed)}
                hint={`${formatDelta(wow.notifications_failed)} · inviate ${cur.notifications.sent}`}
              />
              <MetricCard
                label="Feedback"
                value={String(cur.feedback.total)}
                hint={
                  cur.feedback.avg_rating != null
                    ? `rating ${formatNum(cur.feedback.avg_rating)} · ${formatDelta(wow.feedback_total)}`
                    : formatDelta(wow.feedback_total)
                }
              />
            </div>
            {cur.pipeline.error_messages.length > 0 ? (
              <div className="table-wrap">
                <table>
                  <thead>
                    <tr>
                      <th>Errori pipeline (estratto)</th>
                    </tr>
                  </thead>
                  <tbody>
                    {cur.pipeline.error_messages.map((msg) => (
                      <tr key={msg}>
                        <td>{msg}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ) : null}
          </article>

          <article className="panel">
            <div className="panel-header">
              <h3>Confronto settimana precedente ({prev.week_label})</h3>
            </div>
            <p>
              Precedente: {prev.week_start} → {prev.week_end}. Attivi {prev.users.active_users}, tip{" "}
              {prev.live_tips.predictions_published}, ROI {formatPct(prev.live_tips.roi_pct)},
              notifiche fallite {prev.notifications.failed}, feedback {prev.feedback.total}.
            </p>
            {report.payload.notes.length > 0 ? (
              <ul>
                {report.payload.notes.map((note) => (
                  <li key={note}>{note}</li>
                ))}
              </ul>
            ) : null}
          </article>
        </>
      ) : null}
    </section>
  );
}
