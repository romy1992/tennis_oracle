import { useEffect, useMemo, useState } from "react";

import { MetricCard } from "../components/MetricCard";
import { EmptyState, ErrorState, LoadingState } from "../components/Status";
import { apiClient } from "../services/apiClient";
import type {
  SubscriptionDashboardEventListResponse,
  SubscriptionDashboardSummaryResponse,
  SubscriptionDashboardUserListResponse
} from "../types/api";

const PAGE_SIZE = 50;
const EVENTS_PAGE_SIZE = 50;

type BoolFilter = "" | "true" | "false";
type EventSourceFilter = "" | "payment" | "admin_action";

function formatDateTime(value: string | null) {
  if (!value) return "-";
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return value;
  return parsed.toLocaleString("it-IT", { dateStyle: "short", timeStyle: "short" });
}

function formatPct(value: number | null | undefined) {
  if (value === null || value === undefined) return "-";
  return `${value.toLocaleString("it-IT", { minimumFractionDigits: 1, maximumFractionDigits: 1 })}%`;
}

function formatCurrencyFromCents(value: number | null | undefined) {
  if (value === null || value === undefined) return "-";
  return (value / 100).toLocaleString("it-IT", {
    style: "currency",
    currency: "EUR",
    minimumFractionDigits: 2,
    maximumFractionDigits: 2
  });
}

function parseOptionalBool(value: BoolFilter): boolean | undefined {
  if (value === "") return undefined;
  return value === "true";
}

export function SubscriptionsDashboardPage() {
  const [summary, setSummary] = useState<SubscriptionDashboardSummaryResponse | null>(null);
  const [users, setUsers] = useState<SubscriptionDashboardUserListResponse | null>(null);
  const [events, setEvents] = useState<SubscriptionDashboardEventListResponse | null>(null);
  const [q, setQ] = useState("");
  const [planCode, setPlanCode] = useState("");
  const [subscriptionStatus, setSubscriptionStatus] = useState("");
  const [paymentFailed, setPaymentFailed] = useState<BoolFilter>("");
  const [trialingOnly, setTrialingOnly] = useState(false);
  const [cancelAtPeriodEnd, setCancelAtPeriodEnd] = useState<BoolFilter>("");
  const [expiringWithinDays, setExpiringWithinDays] = useState("");
  const [eventSource, setEventSource] = useState<EventSourceFilter>("");
  const [offset, setOffset] = useState(0);
  const [eventsOffset, setEventsOffset] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [busySubscriptionId, setBusySubscriptionId] = useState<number | null>(null);
  const [exportBusy, setExportBusy] = useState(false);
  const [reloadKey, setReloadKey] = useState(0);

  const activeFilters = useMemo(
    () => {
      const parsedExpiringDays = expiringWithinDays ? Number(expiringWithinDays) : undefined;
      return {
        q: q.trim() || undefined,
        plan_code: planCode || undefined,
        status: subscriptionStatus || undefined,
        payment_failed: parseOptionalBool(paymentFailed),
        trialing_only: trialingOnly || undefined,
        cancel_at_period_end: parseOptionalBool(cancelAtPeriodEnd),
        expiring_within_days:
          parsedExpiringDays !== undefined && Number.isFinite(parsedExpiringDays)
            ? parsedExpiringDays
            : undefined
      };
    },
    [q, planCode, subscriptionStatus, paymentFailed, trialingOnly, cancelAtPeriodEnd, expiringWithinDays]
  );

  useEffect(() => {
    async function load() {
      try {
        setLoading(true);
        const [summaryResponse, usersResponse, eventsResponse] = await Promise.all([
          apiClient.getSubscriptionsDashboardSummary({ months: 6 }),
          apiClient.getSubscriptionsDashboardUsers({
            ...activeFilters,
            limit: PAGE_SIZE,
            offset
          }),
          apiClient.getSubscriptionsDashboardEvents({
            source: eventSource || undefined,
            limit: EVENTS_PAGE_SIZE,
            offset: eventsOffset
          })
        ]);
        setSummary(summaryResponse);
        setUsers(usersResponse);
        setEvents(eventsResponse);
        setError(null);
      } catch (err) {
        setError(err instanceof Error ? err.message : "Errore inatteso.");
      } finally {
        setLoading(false);
      }
    }

    void load();
  }, [activeFilters, eventSource, offset, eventsOffset, reloadKey]);

  async function runAction(
    subscriptionId: number,
    action: "suspend" | "resume" | "cancel"
  ) {
    try {
      setBusySubscriptionId(subscriptionId);
      setActionError(null);
      if (action === "suspend") {
        const reason = window.prompt("Motivazione sospensione (opzionale):", "manual_review");
        await apiClient.suspendDashboardSubscription(subscriptionId, reason?.trim() || undefined);
      } else if (action === "resume") {
        await apiClient.resumeDashboardSubscription(subscriptionId);
      } else {
        const confirmed = window.confirm("Confermi la cancellazione dell'abbonamento?");
        if (!confirmed) return;
        const reason = window.prompt("Motivazione cancellazione (opzionale):", "manual_cancel");
        await apiClient.cancelDashboardSubscription(subscriptionId, {
          immediate: true,
          reason: reason?.trim() || undefined
        });
      }
      setReloadKey((value) => value + 1);
    } catch (err) {
      setActionError(err instanceof Error ? err.message : "Operazione non riuscita.");
    } finally {
      setBusySubscriptionId(null);
    }
  }

  async function exportCsv() {
    try {
      setExportBusy(true);
      setActionError(null);
      const file = await apiClient.exportSubscriptionsDashboardCsv(activeFilters);
      if (typeof window.URL?.createObjectURL !== "function") {
        throw new Error("Download CSV non supportato da questo browser.");
      }
      const url = window.URL.createObjectURL(file.blob);
      const link = document.createElement("a");
      const fallbackName = `subscriptions_dashboard_${new Date().toISOString().slice(0, 10)}.csv`;
      link.href = url;
      link.download = file.filename || fallbackName;
      document.body.appendChild(link);
      link.click();
      link.remove();
      window.URL.revokeObjectURL(url);
    } catch (err) {
      setActionError(err instanceof Error ? err.message : "Esportazione non riuscita.");
    } finally {
      setExportBusy(false);
    }
  }

  if (loading && (!summary || !users || !events)) {
    return <LoadingState title="Caricamento dashboard abbonamenti..." />;
  }
  if (error && (!summary || !users || !events)) {
    return <ErrorState title="Dashboard abbonamenti non disponibile" message={error} />;
  }

  const overview = summary?.overview;
  const userItems = users?.items ?? [];
  const userTotal = users?.total ?? 0;
  const eventsItems = events?.items ?? [];
  const eventsTotal = events?.total ?? 0;

  return (
    <section className="page">
      <header className="page-header">
        <div>
          <h2>Dashboard abbonamenti</h2>
          <p>
            Monitoraggio utenti Free/Pro/Founder, conversione, churn, eventi pagamento e azioni
            manuali admin.
          </p>
        </div>
        <div className="page-header-actions">
          <button
            type="button"
            className="action-button primary"
            disabled={exportBusy}
            onClick={() => void exportCsv()}
          >
            {exportBusy ? "Esportazione..." : "Esporta CSV"}
          </button>
        </div>
      </header>

      <div className="metrics-grid">
        <MetricCard label="Utenti Free" value={String(overview?.users_free ?? 0)} />
        <MetricCard label="Utenti Pro" value={String(overview?.users_pro ?? 0)} />
        <MetricCard label="Utenti Founder" value={String(overview?.users_founder ?? 0)} />
        <MetricCard label="Abbonamenti attivi" value={String(overview?.active_subscriptions ?? 0)} />
        <MetricCard label="In prova" value={String(overview?.trialing_subscriptions ?? 0)} />
        <MetricCard
          label="Scadenze <= 30g"
          value={String(overview?.expiring_within_30_days ?? 0)}
        />
        <MetricCard
          label="Pagamenti falliti (30g)"
          value={String(overview?.payment_failed_last_30_days ?? 0)}
        />
        <MetricCard
          label="Entrate mese"
          value={formatCurrencyFromCents(overview?.monthly_revenue_cents)}
        />
        <MetricCard
          label="Conversione Free->Pro"
          value={formatPct(overview?.free_to_pro_conversion_pct)}
        />
        <MetricCard label="Churn (30g)" value={formatPct(overview?.churn_pct_last_30_days)} />
      </div>

      <article className="panel">
        <div className="panel-header">
          <h3>Filtri utenti</h3>
          <span className="pill">{userTotal} risultati</span>
        </div>
        <div className="filters-grid">
          <label>
            Ricerca
            <input
              value={q}
              onChange={(event) => {
                setOffset(0);
                setQ(event.target.value);
              }}
              placeholder="username, external_ref, telegram id"
            />
          </label>
          <label>
            Piano
            <select
              value={planCode}
              onChange={(event) => {
                setOffset(0);
                setPlanCode(event.target.value);
              }}
            >
              <option value="">Tutti</option>
              <option value="free">Free</option>
              <option value="pro">Pro</option>
              <option value="founder">Founder</option>
            </select>
          </label>
          <label>
            Stato
            <select
              value={subscriptionStatus}
              onChange={(event) => {
                setOffset(0);
                setSubscriptionStatus(event.target.value);
              }}
            >
              <option value="">Tutti</option>
              <option value="trialing">Trialing</option>
              <option value="active">Active</option>
              <option value="suspended">Suspended</option>
              <option value="canceled">Canceled</option>
              <option value="expired">Expired</option>
            </select>
          </label>
          <label>
            Pagamento fallito
            <select
              value={paymentFailed}
              onChange={(event) => {
                setOffset(0);
                setPaymentFailed(event.target.value as BoolFilter);
              }}
            >
              <option value="">Tutti</option>
              <option value="true">Solo con fallimenti</option>
              <option value="false">Solo senza fallimenti</option>
            </select>
          </label>
          <label>
            Scadenza entro (giorni)
            <input
              type="number"
              min={0}
              max={365}
              value={expiringWithinDays}
              onChange={(event) => {
                setOffset(0);
                setExpiringWithinDays(event.target.value);
              }}
              placeholder="es. 30"
            />
          </label>
          <label>
            Cancellazione a fine periodo
            <select
              value={cancelAtPeriodEnd}
              onChange={(event) => {
                setOffset(0);
                setCancelAtPeriodEnd(event.target.value as BoolFilter);
              }}
            >
              <option value="">Tutti</option>
              <option value="true">Si</option>
              <option value="false">No</option>
            </select>
          </label>
          <label className="checkbox-field">
            <input
              type="checkbox"
              checked={trialingOnly}
              onChange={(event) => {
                setOffset(0);
                setTrialingOnly(event.target.checked);
              }}
            />
            Solo in prova
          </label>
        </div>
      </article>

      {actionError ? <ErrorState title="Operazione non riuscita" message={actionError} /> : null}
      {error ? <ErrorState title="Aggiornamento dashboard" message={error} /> : null}

      <article className="panel">
        <div className="panel-header">
          <h3>Utenti e abbonamenti</h3>
          <span className="pill">
            Pagina {Math.floor(offset / PAGE_SIZE) + 1} / {Math.max(1, Math.ceil(userTotal / PAGE_SIZE))}
          </span>
        </div>

        {userItems.length === 0 ? (
          <EmptyState
            title="Nessun utente"
            message="Nessun utente trovato con i filtri selezionati."
          />
        ) : (
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Utente</th>
                  <th>Piano</th>
                  <th>Stato</th>
                  <th>Prova</th>
                  <th>Scadenza</th>
                  <th>Auto renew</th>
                  <th>Pagamenti</th>
                  <th>Azioni</th>
                </tr>
              </thead>
              <tbody>
                {userItems.map((row) => {
                  const busy = busySubscriptionId === row.subscription_id;
                  const canSuspend = row.subscription_status === "active" || row.subscription_status === "trialing";
                  const canResume = row.subscription_status === "suspended";
                  const canCancel =
                    row.subscription_status !== "canceled" &&
                    row.subscription_status !== "expired" &&
                    row.subscription_id !== null;
                  return (
                    <tr key={row.user_id}>
                      <td>
                        {row.username ? `@${row.username}` : "-"}
                        <br />
                        <small>uid:{row.user_id}</small>
                        <br />
                        <small>tg:{row.telegram_user_id ?? "-"}</small>
                      </td>
                      <td>{row.plan_name || row.plan_code || "-"}</td>
                      <td>{row.subscription_status || "-"}</td>
                      <td>{formatDateTime(row.trial_ends_at)}</td>
                      <td>{formatDateTime(row.expires_at)}</td>
                      <td>{row.auto_renew ? "Sì" : "No"}</td>
                      <td>{row.payment_failed ? "Fallito" : row.last_payment_status || "-"}</td>
                      <td>
                        <div className="page-header-actions">
                          <button
                            type="button"
                            className="action-button secondary"
                            disabled={busy || !row.subscription_id || !canSuspend}
                            onClick={() =>
                              row.subscription_id && void runAction(row.subscription_id, "suspend")
                            }
                          >
                            Sospendi
                          </button>
                          <button
                            type="button"
                            className="action-button secondary"
                            disabled={busy || !row.subscription_id || !canResume}
                            onClick={() =>
                              row.subscription_id && void runAction(row.subscription_id, "resume")
                            }
                          >
                            Riattiva
                          </button>
                          <button
                            type="button"
                            className="action-button secondary"
                            disabled={busy || !row.subscription_id || !canCancel}
                            onClick={() =>
                              row.subscription_id && void runAction(row.subscription_id, "cancel")
                            }
                          >
                            Cancella
                          </button>
                        </div>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}

        <div className="pagination">
          <button
            type="button"
            className="action-button"
            disabled={offset <= 0 || loading}
            onClick={() => setOffset((value) => Math.max(0, value - PAGE_SIZE))}
          >
            Precedente
          </button>
          <span className="pagination-label">
            {Math.min(offset + 1, userTotal)}–{Math.min(offset + PAGE_SIZE, userTotal)} di {userTotal}
          </span>
          <button
            type="button"
            className="action-button"
            disabled={offset + PAGE_SIZE >= userTotal || loading}
            onClick={() => setOffset((value) => value + PAGE_SIZE)}
          >
            Successiva
          </button>
        </div>
      </article>

      <article className="panel">
        <div className="panel-header">
          <h3>Entrate mensili</h3>
        </div>
        {summary && summary.monthly_revenue.length > 0 ? (
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Mese</th>
                  <th>Entrate</th>
                </tr>
              </thead>
              <tbody>
                {summary.monthly_revenue.map((row) => (
                  <tr key={row.month}>
                    <td>{row.month}</td>
                    <td>{formatCurrencyFromCents(row.revenue_cents)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <EmptyState title="Nessuna entrata" message="Nessun dato entrate disponibile." />
        )}
      </article>

      <article className="panel">
        <div className="panel-header">
          <h3>Storico eventi</h3>
          <div className="page-header-actions">
            <label>
              Sorgente
              <select
                value={eventSource}
                onChange={(event) => {
                  setEventsOffset(0);
                  setEventSource(event.target.value as EventSourceFilter);
                }}
              >
                <option value="">Tutte</option>
                <option value="payment">Pagamenti</option>
                <option value="admin_action">Azioni admin</option>
              </select>
            </label>
          </div>
        </div>

        {eventsItems.length === 0 ? (
          <EmptyState title="Nessun evento" message="Nessun evento disponibile con questi filtri." />
        ) : (
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Data</th>
                  <th>Sorgente</th>
                  <th>Evento</th>
                  <th>Stato</th>
                  <th>Utente</th>
                  <th>Importo</th>
                  <th>Admin</th>
                  <th>Dettaglio</th>
                </tr>
              </thead>
              <tbody>
                {eventsItems.map((row) => (
                  <tr key={row.event_id}>
                    <td>{formatDateTime(row.occurred_at)}</td>
                    <td>{row.source}</td>
                    <td>{row.event_type}</td>
                    <td>{row.status || "-"}</td>
                    <td>{row.user_id ?? "-"}</td>
                    <td>{formatCurrencyFromCents(row.amount_cents)}</td>
                    <td>{row.admin_username || "-"}</td>
                    <td>{row.description || "-"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}

        <div className="pagination">
          <button
            type="button"
            className="action-button"
            disabled={eventsOffset <= 0 || loading}
            onClick={() => setEventsOffset((value) => Math.max(0, value - EVENTS_PAGE_SIZE))}
          >
            Precedente
          </button>
          <span className="pagination-label">
            {Math.min(eventsOffset + 1, eventsTotal)}–
            {Math.min(eventsOffset + EVENTS_PAGE_SIZE, eventsTotal)} di {eventsTotal}
          </span>
          <button
            type="button"
            className="action-button"
            disabled={eventsOffset + EVENTS_PAGE_SIZE >= eventsTotal || loading}
            onClick={() => setEventsOffset((value) => value + EVENTS_PAGE_SIZE)}
          >
            Successiva
          </button>
        </div>
      </article>
    </section>
  );
}


