import { useEffect, useMemo, useState } from "react";

import { MetricCard } from "../components/MetricCard";
import { EmptyState, ErrorState, LoadingState } from "../components/Status";
import { apiClient } from "../services/apiClient";
import type {
  TelegramBotEvent,
  TelegramBotEventsResponse,
  TelegramBotStatsResponse
} from "../types/api";
import { formatDate, todayLocalISODate } from "../utils/tennis";

const PAGE_SIZE = 50;
const DAYS_PAGE_SIZE = 5;

function todayIso() {
  return todayLocalISODate();
}

function daysAgoIso(days: number) {
  const value = new Date();
  value.setDate(value.getDate() - days);
  return todayLocalISODate(value);
}

function formatDateTime(value: string) {
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return value;
  return parsed.toLocaleString("it-IT", {
    dateStyle: "short",
    timeStyle: "medium"
  });
}

function displayName(event: TelegramBotEvent) {
  const parts = [event.first_name, event.last_name].filter(Boolean);
  if (event.username) {
    return `@${event.username}${parts.length ? ` (${parts.join(" ")})` : ""}`;
  }
  if (parts.length) return parts.join(" ");
  return event.telegram_user_id != null ? String(event.telegram_user_id) : "-";
}

function successLabel(value: boolean | null) {
  if (value === true) return "ok";
  if (value === false) return "errore";
  return "-";
}

export function TelegramBotPage() {
  const [stats, setStats] = useState<TelegramBotStatsResponse | null>(null);
  const [events, setEvents] = useState<TelegramBotEventsResponse | null>(null);
  const [fromDate, setFromDate] = useState(() => daysAgoIso(30));
  const [toDate, setToDate] = useState(() => todayIso());
  const [action, setAction] = useState("");
  const [userId, setUserId] = useState("");
  const [username, setUsername] = useState("");
  const [offset, setOffset] = useState(0);
  const [daysPage, setDaysPage] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    async function load() {
      try {
        setLoading(true);
        const parsedUserId = userId.trim() ? Number(userId.trim()) : undefined;
        const [statsData, eventsData] = await Promise.all([
          apiClient.getTelegramBotStats({ from: fromDate, to: toDate }),
          apiClient.getTelegramBotEvents({
            from: fromDate,
            to: toDate,
            action: action.trim() || undefined,
            user_id:
              parsedUserId !== undefined && Number.isFinite(parsedUserId)
                ? parsedUserId
                : undefined,
            username: username.trim() || undefined,
            limit: PAGE_SIZE,
            offset
          })
        ]);
        setStats(statsData);
        setEvents(eventsData);
        setError(null);
      } catch (err) {
        setError(err instanceof Error ? err.message : "Errore inatteso.");
      } finally {
        setLoading(false);
      }
    }
    void load();
  }, [fromDate, toDate, action, userId, username, offset]);

  const daysNewestFirst = useMemo(() => {
    return [...(stats?.by_day ?? [])].sort((left, right) => right.day.localeCompare(left.day));
  }, [stats]);

  const daysTotalPages = Math.max(1, Math.ceil(daysNewestFirst.length / DAYS_PAGE_SIZE));
  const safeDaysPage = Math.min(daysPage, daysTotalPages - 1);
  const visibleDays = daysNewestFirst.slice(
    safeDaysPage * DAYS_PAGE_SIZE,
    safeDaysPage * DAYS_PAGE_SIZE + DAYS_PAGE_SIZE
  );
  const maxDayCount = Math.max(1, ...daysNewestFirst.map((day) => day.count), 1);

  if (loading && !stats && !events) {
    return <LoadingState title="Caricamento accessi bot..." />;
  }

  if (error && !stats && !events) {
    return <ErrorState title="Accessi bot non disponibili" message={error} />;
  }

  return (
    <section className="page">
      <header className="page-header">
        <div>
          <h2>Bot Telegram</h2>
          <p>
            Accessi e comandi degli utenti del bot (solo admin). Periodo {formatDate(fromDate)} –{" "}
            {formatDate(toDate)}.
          </p>
        </div>
      </header>

      {error ? <ErrorState title="Aggiornamento parziale" message={error} /> : null}

      <div className="metrics-grid">
        <MetricCard label="Eventi totali" value={stats?.total_events ?? 0} />
        <MetricCard label="Utenti unici" value={stats?.unique_users ?? 0} />
        <MetricCard label="Eventi oggi" value={stats?.events_today ?? 0} />
        <MetricCard label="Comando più usato" value={stats?.top_action ?? "-"} />
      </div>

      <article className="panel">
        <div className="panel-header">
          <h3>Filtri</h3>
        </div>
        <div className="filters-grid compact">
          <label>
            Da
            <input
              type="date"
              value={fromDate}
              onChange={(event) => {
                setOffset(0);
                setDaysPage(0);
                setFromDate(event.target.value);
              }}
            />
          </label>
          <label>
            A
            <input
              type="date"
              value={toDate}
              onChange={(event) => {
                setOffset(0);
                setDaysPage(0);
                setToDate(event.target.value);
              }}
            />
          </label>
          <label>
            Comando / azione
            <input
              type="text"
              placeholder="/schedine"
              value={action}
              onChange={(event) => {
                setOffset(0);
                setAction(event.target.value);
              }}
            />
          </label>
          <label>
            User ID
            <input
              type="text"
              inputMode="numeric"
              placeholder="123456"
              value={userId}
              onChange={(event) => {
                setOffset(0);
                setUserId(event.target.value);
              }}
            />
          </label>
          <label>
            Username
            <input
              type="text"
              placeholder="nomeutente"
              value={username}
              onChange={(event) => {
                setOffset(0);
                setUsername(event.target.value);
              }}
            />
          </label>
        </div>
      </article>

      <article className="panel">
        <div className="panel-header">
          <h3>Comandi / azioni</h3>
        </div>
        {(stats?.by_action.length ?? 0) === 0 ? (
          <EmptyState title="Nessun comando nel periodo" />
        ) : (
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Azione</th>
                  <th>Conteggi</th>
                </tr>
              </thead>
              <tbody>
                {stats?.by_action.map((row) => (
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
          <h3>Serie giornaliera</h3>
          <span className="pill">5 giorni · dalla più recente</span>
        </div>
        {daysNewestFirst.length === 0 ? (
          <EmptyState title="Nessun giorno nel periodo" />
        ) : (
          <>
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
                  ? `${formatDate(visibleDays[0].day)} – ${formatDate(visibleDays[visibleDays.length - 1].day)}`
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
            <div className="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th>Giorno</th>
                    <th>Eventi</th>
                    <th>Andamento</th>
                  </tr>
                </thead>
                <tbody>
                  {visibleDays.map((row) => (
                    <tr key={row.day}>
                      <td>{formatDate(row.day)}</td>
                      <td>{row.count}</td>
                      <td>
                        <div
                          className="mini-bar"
                          style={{
                            width: `${Math.max(4, (row.count / maxDayCount) * 100)}%`
                          }}
                          title={`${row.count} eventi`}
                        />
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </>
        )}
      </article>

      <article className="panel">
        <div className="panel-header">
          <h3>Accessi recenti</h3>
          <span className="pill">
            {events
              ? `${Math.min(events.offset + 1, events.total)}–${Math.min(events.offset + events.items.length, events.total)} di ${events.total}`
              : "0"}
          </span>
        </div>
        {(events?.items.length ?? 0) === 0 ? (
          <EmptyState
            title="Nessun accesso registrato"
            message="Gli eventi compariranno quando qualcuno userà il bot."
          />
        ) : (
          <>
            <div className="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th>Data/ora</th>
                    <th>Utente</th>
                    <th>User ID</th>
                    <th>Chat ID</th>
                    <th>Tipo</th>
                    <th>Azione</th>
                    <th>Esito</th>
                    <th>Errore</th>
                  </tr>
                </thead>
                <tbody>
                  {events?.items.map((event) => (
                    <tr key={event.id}>
                      <td>{formatDateTime(event.created_at)}</td>
                      <td>{displayName(event)}</td>
                      <td>{event.telegram_user_id ?? "-"}</td>
                      <td>{event.chat_id ?? "-"}</td>
                      <td>{event.event_type}</td>
                      <td>{event.action}</td>
                      <td>{successLabel(event.success)}</td>
                      <td>{event.error_message ?? "-"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <div className="page-header-actions" style={{ marginTop: "1rem" }}>
              <button
                type="button"
                className="action-button secondary"
                disabled={offset <= 0 || loading}
                onClick={() => setOffset((current) => Math.max(0, current - PAGE_SIZE))}
              >
                Precedenti
              </button>
              <button
                type="button"
                className="action-button secondary"
                disabled={
                  loading || !events || events.offset + events.items.length >= events.total
                }
                onClick={() => setOffset((current) => current + PAGE_SIZE)}
              >
                Successivi
              </button>
            </div>
          </>
        )}
      </article>
    </section>
  );
}
