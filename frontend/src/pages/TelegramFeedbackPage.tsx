import { useEffect, useState } from "react";

import { MetricCard } from "../components/MetricCard";
import { EmptyState, ErrorState, LoadingState } from "../components/Status";
import { apiClient } from "../services/apiClient";
import type {
  TelegramFeedback,
  TelegramFeedbackCategory,
  TelegramFeedbackListResponse,
  TelegramFeedbackStatus
} from "../types/api";

const PAGE_SIZE = 50;

const STATUS_OPTIONS: Array<{ value: "" | TelegramFeedbackStatus; label: string }> = [
  { value: "", label: "Tutti gli stati" },
  { value: "new", label: "New" },
  { value: "reviewing", label: "Reviewing" },
  { value: "resolved", label: "Resolved" },
  { value: "rejected", label: "Rejected" }
];

const CATEGORY_OPTIONS: Array<{ value: "" | TelegramFeedbackCategory; label: string }> = [
  { value: "", label: "Tutte le categorie" },
  { value: "bug", label: "Bug / errore" },
  { value: "content", label: "Contenuti" },
  { value: "ux", label: "Usabilità" },
  { value: "feature", label: "Suggerimento" },
  { value: "access", label: "Accesso" },
  { value: "other", label: "Altro" }
];

const CATEGORY_LABELS: Record<string, string> = Object.fromEntries(
  CATEGORY_OPTIONS.filter((option) => option.value).map((option) => [
    option.value,
    option.label
  ])
);

function formatDateTime(value: string | null) {
  if (!value) return "-";
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return value;
  return parsed.toLocaleString("it-IT", {
    dateStyle: "short",
    timeStyle: "medium"
  });
}

function displayUser(item: TelegramFeedback) {
  const parts = [item.first_name, item.last_name].filter(Boolean);
  if (item.username) {
    return `@${item.username}${parts.length ? ` (${parts.join(" ")})` : ""}`;
  }
  if (parts.length) return parts.join(" ");
  return String(item.telegram_user_id);
}

export function TelegramFeedbackPage() {
  const [data, setData] = useState<TelegramFeedbackListResponse | null>(null);
  const [q, setQ] = useState("");
  const [status, setStatus] = useState<"" | TelegramFeedbackStatus>("");
  const [category, setCategory] = useState<"" | TelegramFeedbackCategory>("");
  const [offset, setOffset] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [busyId, setBusyId] = useState<number | null>(null);
  const [reloadKey, setReloadKey] = useState(0);

  useEffect(() => {
    async function load() {
      try {
        setLoading(true);
        const response = await apiClient.getTelegramFeedback({
          q: q.trim() || undefined,
          status: status || undefined,
          category: category || undefined,
          limit: PAGE_SIZE,
          offset
        });
        setData(response);
        setError(null);
      } catch (err) {
        setError(err instanceof Error ? err.message : "Errore inatteso.");
      } finally {
        setLoading(false);
      }
    }
    void load();
  }, [q, status, category, offset, reloadKey]);

  async function setFeedbackStatus(feedbackId: number, next: TelegramFeedbackStatus) {
    try {
      setBusyId(feedbackId);
      setActionError(null);
      await apiClient.updateTelegramFeedbackStatus(feedbackId, { status: next });
      setReloadKey((value) => value + 1);
    } catch (err) {
      setActionError(err instanceof Error ? err.message : "Aggiornamento stato non riuscito.");
    } finally {
      setBusyId(null);
    }
  }

  if (loading && !data) return <LoadingState />;
  if (error && !data) {
    return <ErrorState title="Feedback Telegram non disponibili" message={error} />;
  }

  const items = data?.items ?? [];
  const total = data?.total ?? 0;
  const page = Math.floor(offset / PAGE_SIZE) + 1;
  const totalPages = Math.max(1, Math.ceil(total / PAGE_SIZE));
  const newCount = items.filter((item) => item.status === "new").length;
  const reviewingCount = items.filter((item) => item.status === "reviewing").length;
  const closedCount = items.filter(
    (item) => item.status === "resolved" || item.status === "rejected"
  ).length;

  return (
    <section className="page">
      <header className="page-header">
        <div>
          <h2>Feedback Telegram</h2>
          <p>
            Inbox dei feedback inviati con /feedback: categoria, valutazione, messaggio e
            stato di lavorazione.
          </p>
        </div>
      </header>

      <div className="metrics-grid">
        <MetricCard label="Feedback (filtro)" value={String(total)} />
        <MetricCard label="New (pagina)" value={String(newCount)} />
        <MetricCard label="Reviewing (pagina)" value={String(reviewingCount)} />
        <MetricCard label="Chiusi (pagina)" value={String(closedCount)} />
      </div>

      <article className="panel">
        <div className="panel-header">
          <h3>Filtri</h3>
        </div>
        <div className="filters-grid compact">
          <label>
            Ricerca
            <input
              value={q}
              onChange={(event) => {
                setOffset(0);
                setQ(event.target.value);
              }}
              placeholder="id, utente, messaggio…"
            />
          </label>
          <label>
            Stato
            <select
              value={status}
              onChange={(event) => {
                setOffset(0);
                setStatus(event.target.value as "" | TelegramFeedbackStatus);
              }}
            >
              {STATUS_OPTIONS.map((option) => (
                <option key={option.value || "all-status"} value={option.value}>
                  {option.label}
                </option>
              ))}
            </select>
          </label>
          <label>
            Categoria
            <select
              value={category}
              onChange={(event) => {
                setOffset(0);
                setCategory(event.target.value as "" | TelegramFeedbackCategory);
              }}
            >
              {CATEGORY_OPTIONS.map((option) => (
                <option key={option.value || "all-category"} value={option.value}>
                  {option.label}
                </option>
              ))}
            </select>
          </label>
        </div>
      </article>

      {actionError ? <ErrorState title="Operazione non riuscita" message={actionError} /> : null}
      {error ? <ErrorState title="Aggiornamento elenco" message={error} /> : null}

      <article className="panel">
        <div className="panel-header">
          <h3>Feedback</h3>
          <span className="pill">
            Pagina {page} / {totalPages}
          </span>
        </div>
        {items.length === 0 ? (
          <EmptyState
            title="Nessun feedback"
            message="Nessun feedback trovato con i filtri correnti."
          />
        ) : (
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>ID</th>
                  <th>Utente</th>
                  <th>Categoria</th>
                  <th>Voto</th>
                  <th>Messaggio</th>
                  <th>Stato</th>
                  <th>Creato</th>
                  <th>Azioni</th>
                </tr>
              </thead>
              <tbody>
                {items.map((item) => {
                  const busy = busyId === item.id;
                  return (
                    <tr key={item.id}>
                      <td>#{item.id}</td>
                      <td>
                        <div>{displayUser(item)}</div>
                        <div className="muted">{item.telegram_user_id}</div>
                      </td>
                      <td>{CATEGORY_LABELS[item.category] ?? item.category}</td>
                      <td>{item.rating}/5</td>
                      <td className="wrap-cell">{item.message}</td>
                      <td>{item.status}</td>
                      <td>{formatDateTime(item.created_at)}</td>
                      <td>
                        <div className="row-actions">
                          {item.status !== "reviewing" ? (
                            <button
                              type="button"
                              className="action-button"
                              disabled={busy}
                              onClick={() => void setFeedbackStatus(item.id, "reviewing")}
                            >
                              Reviewing
                            </button>
                          ) : null}
                          {item.status !== "resolved" ? (
                            <button
                              type="button"
                              className="action-button primary"
                              disabled={busy}
                              onClick={() => void setFeedbackStatus(item.id, "resolved")}
                            >
                              Resolved
                            </button>
                          ) : null}
                          {item.status !== "rejected" ? (
                            <button
                              type="button"
                              className="action-button"
                              disabled={busy}
                              onClick={() => void setFeedbackStatus(item.id, "rejected")}
                            >
                              Rejected
                            </button>
                          ) : null}
                          {item.status !== "new" ? (
                            <button
                              type="button"
                              className="action-button"
                              disabled={busy}
                              onClick={() => void setFeedbackStatus(item.id, "new")}
                            >
                              New
                            </button>
                          ) : null}
                        </div>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
        <div className="page-header-actions">
          <button
            type="button"
            className="action-button"
            disabled={offset <= 0 || loading}
            onClick={() => setOffset(Math.max(0, offset - PAGE_SIZE))}
          >
            Precedente
          </button>
          <button
            type="button"
            className="action-button"
            disabled={offset + PAGE_SIZE >= total || loading}
            onClick={() => setOffset(offset + PAGE_SIZE)}
          >
            Successiva
          </button>
        </div>
      </article>
    </section>
  );
}
