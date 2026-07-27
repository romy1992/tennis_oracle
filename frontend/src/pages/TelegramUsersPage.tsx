import { useEffect, useState, type FormEvent } from "react";

import { MetricCard } from "../components/MetricCard";
import { EmptyState, ErrorState, LoadingState } from "../components/Status";
import { apiClient } from "../services/apiClient";
import type { TelegramUser, TelegramUserListResponse, TelegramUserStatus } from "../types/api";

const PAGE_SIZE = 50;
const STATUS_OPTIONS: Array<{ value: "" | TelegramUserStatus; label: string }> = [
  { value: "", label: "Tutti gli stati" },
  { value: "invited", label: "Invited" },
  { value: "active", label: "Active" },
  { value: "suspended", label: "Suspended" },
  { value: "blocked", label: "Blocked" }
];

function formatDateTime(value: string | null) {
  if (!value) return "-";
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return value;
  return parsed.toLocaleString("it-IT", {
    dateStyle: "short",
    timeStyle: "medium"
  });
}

function displayName(user: TelegramUser) {
  const parts = [user.first_name, user.last_name].filter(Boolean);
  if (user.username) {
    return `@${user.username}${parts.length ? ` (${parts.join(" ")})` : ""}`;
  }
  if (parts.length) return parts.join(" ");
  return String(user.telegram_user_id);
}

export function TelegramUsersPage() {
  const [data, setData] = useState<TelegramUserListResponse | null>(null);
  const [q, setQ] = useState("");
  const [status, setStatus] = useState<"" | TelegramUserStatus>("");
  const [offset, setOffset] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [busyId, setBusyId] = useState<number | null>(null);
  const [inviteUserId, setInviteUserId] = useState("");
  const [inviteUsername, setInviteUsername] = useState("");
  const [inviteOrigin, setInviteOrigin] = useState("");
  const [inviteBusy, setInviteBusy] = useState(false);
  const [reloadKey, setReloadKey] = useState(0);

  useEffect(() => {
    async function load() {
      try {
        setLoading(true);
        const response = await apiClient.getTelegramUsers({
          q: q.trim() || undefined,
          status: status || undefined,
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
  }, [q, status, offset, reloadKey]);

  async function runStatusAction(
    telegramUserId: number,
    action: "activate" | "suspend" | "block"
  ) {
    try {
      setBusyId(telegramUserId);
      setActionError(null);
      if (action === "activate") {
        await apiClient.activateTelegramUser(telegramUserId);
      } else if (action === "suspend") {
        await apiClient.suspendTelegramUser(telegramUserId);
      } else {
        await apiClient.blockTelegramUser(telegramUserId);
      }
      setReloadKey((value) => value + 1);
    } catch (err) {
      setActionError(err instanceof Error ? err.message : "Azione non riuscita.");
    } finally {
      setBusyId(null);
    }
  }

  async function inviteUser(event: FormEvent) {
    event.preventDefault();
    const parsedId = Number(inviteUserId.trim());
    if (!Number.isFinite(parsedId) || parsedId <= 0) {
      setActionError("Inserisci un telegram_user_id numerico valido.");
      return;
    }
    try {
      setInviteBusy(true);
      setActionError(null);
      await apiClient.inviteTelegramUser({
        telegram_user_id: parsedId,
        username: inviteUsername.trim() || undefined,
        invite_origin: inviteOrigin.trim() || undefined,
        status: "invited"
      });
      setInviteUserId("");
      setInviteUsername("");
      setInviteOrigin("");
      setOffset(0);
      setReloadKey((value) => value + 1);
    } catch (err) {
      setActionError(err instanceof Error ? err.message : "Invito non riuscito.");
    } finally {
      setInviteBusy(false);
    }
  }

  if (loading && !data) return <LoadingState />;
  if (error && !data) {
    return <ErrorState title="Utenti Telegram non disponibili" message={error} />;
  }

  const items = data?.items ?? [];
  const total = data?.total ?? 0;
  const page = Math.floor(offset / PAGE_SIZE) + 1;
  const totalPages = Math.max(1, Math.ceil(total / PAGE_SIZE));
  const activeCount = items.filter((item) => item.status === "active").length;
  const invitedCount = items.filter((item) => item.status === "invited").length;
  const blockedCount = items.filter(
    (item) => item.status === "blocked" || item.status === "suspended"
  ).length;

  return (
    <section className="page">
      <header className="page-header">
        <div>
          <h2>Utenti beta Telegram</h2>
          <p>
            Whitelist e stati di accesso del bot. Cerca, invita, attiva, sospendi o blocca.
          </p>
        </div>
      </header>

      <div className="metrics-grid">
        <MetricCard label="Utenti (filtro)" value={String(total)} />
        <MetricCard label="Active (pagina)" value={String(activeCount)} />
        <MetricCard label="Invited (pagina)" value={String(invitedCount)} />
        <MetricCard label="Sospesi/bloccati (pagina)" value={String(blockedCount)} />
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
              placeholder="id, username, nome, invito…"
            />
          </label>
          <label>
            Stato
            <select
              value={status}
              onChange={(event) => {
                setOffset(0);
                setStatus(event.target.value as "" | TelegramUserStatus);
              }}
            >
              {STATUS_OPTIONS.map((option) => (
                <option key={option.value || "all"} value={option.value}>
                  {option.label}
                </option>
              ))}
            </select>
          </label>
        </div>
      </article>

      <article className="panel">
        <div className="panel-header">
          <h3>Invita utente</h3>
        </div>
        <form className="filters-grid compact" onSubmit={inviteUser}>
          <label>
            Telegram user id
            <input
              value={inviteUserId}
              onChange={(event) => setInviteUserId(event.target.value)}
              placeholder="123456789"
              required
            />
          </label>
          <label>
            Username (opz.)
            <input
              value={inviteUsername}
              onChange={(event) => setInviteUsername(event.target.value)}
              placeholder="nome_utente"
            />
          </label>
          <label>
            Origine invito (opz.)
            <input
              value={inviteOrigin}
              onChange={(event) => setInviteOrigin(event.target.value)}
              placeholder="beta_wave1"
            />
          </label>
          <div className="page-header-actions">
            <button className="action-button primary" type="submit" disabled={inviteBusy}>
              {inviteBusy ? "Invio…" : "Aggiungi invited"}
            </button>
          </div>
        </form>
      </article>

      {actionError ? <ErrorState title="Operazione non riuscita" message={actionError} /> : null}
      {error ? <ErrorState title="Aggiornamento elenco" message={error} /> : null}

      <article className="panel">
        <div className="panel-header">
          <h3>Utenti</h3>
          <span className="pill">
            Pagina {page} / {totalPages}
          </span>
        </div>
        {items.length === 0 ? (
          <EmptyState
            title="Nessun utente"
            message="Nessun utente beta trovato con i filtri correnti."
          />
        ) : (
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Utente</th>
                  <th>Telegram ID</th>
                  <th>Stato</th>
                  <th>Invito</th>
                  <th>Condizioni</th>
                  <th>Notifiche</th>
                  <th>Primo accesso</th>
                  <th>Ultimo accesso</th>
                  <th>Azioni</th>
                </tr>
              </thead>
              <tbody>
                {items.map((user) => {
                  const busy = busyId === user.telegram_user_id;
                  return (
                    <tr key={user.id}>
                      <td>{displayName(user)}</td>
                      <td>{user.telegram_user_id}</td>
                      <td>{user.status}</td>
                      <td>{user.invite_origin || "-"}</td>
                      <td>
                        {user.terms_accepted
                          ? `sì${user.terms_version ? ` (v${user.terms_version})` : ""}`
                          : "no"}
                      </td>
                      <td>
                        {user.notifications_enabled === false
                          ? "off"
                          : [
                              user.notify_predictions !== false ? "P" : null,
                              user.notify_results !== false ? "R" : null,
                              user.notify_empty_day ? "V" : null
                            ]
                              .filter(Boolean)
                              .join("/") || "off"}
                      </td>
                      <td>{formatDateTime(user.first_access_at)}</td>
                      <td>{formatDateTime(user.last_access_at)}</td>
                      <td>
                        <div className="page-header-actions">
                          <button
                            type="button"
                            className="action-button secondary"
                            disabled={busy || user.status === "active"}
                            onClick={() => void runStatusAction(user.telegram_user_id, "activate")}
                          >
                            Attiva
                          </button>
                          <button
                            type="button"
                            className="action-button secondary"
                            disabled={busy || user.status === "suspended"}
                            onClick={() => void runStatusAction(user.telegram_user_id, "suspend")}
                          >
                            Sospendi
                          </button>
                          <button
                            type="button"
                            className="action-button secondary"
                            disabled={busy || user.status === "blocked"}
                            onClick={() => void runStatusAction(user.telegram_user_id, "block")}
                          >
                            Blocca
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
            {offset + 1}–{Math.min(offset + PAGE_SIZE, total)} di {total}
          </span>
          <button
            type="button"
            className="action-button"
            disabled={offset + PAGE_SIZE >= total || loading}
            onClick={() => setOffset((value) => value + PAGE_SIZE)}
          >
            Successiva
          </button>
        </div>
      </article>
    </section>
  );
}
