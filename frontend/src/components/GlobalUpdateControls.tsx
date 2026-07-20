import { useState } from "react";
import { Link } from "react-router-dom";

import { useGlobalUpdate } from "../hooks/useGlobalUpdate";
import { ApiError } from "../services/apiClient";

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

export function GlobalUpdateControls() {
  const { status, isRunning, triggerUpdate, cancelUpdate, lastCompletedAt, lastOrigin } =
    useGlobalUpdate();
  const [actionError, setActionError] = useState<string | null>(null);
  const [cancelling, setCancelling] = useState(false);

  async function handleClick() {
    try {
      setActionError(null);
      await triggerUpdate(true);
    } catch (err) {
      const message =
        err instanceof ApiError
          ? err.message
          : err instanceof Error
            ? err.message
            : "Errore durante l'aggiornamento globale.";
      setActionError(message);
    }
  }

  async function handleCancel() {
    try {
      setActionError(null);
      setCancelling(true);
      await cancelUpdate();
    } catch (err) {
      const message =
        err instanceof ApiError
          ? err.message
          : err instanceof Error
            ? err.message
            : "Errore durante l'annullamento.";
      setActionError(message);
    } finally {
      setCancelling(false);
    }
  }

  return (
    <div className="global-update-controls">
      <div className="global-update-actions">
        <button
          type="button"
          className="action-button primary"
          onClick={() => void handleClick()}
          disabled={isRunning}
        >
          {isRunning ? "Aggiornamento globale..." : "Aggiorna tutto"}
        </button>
        {isRunning && status ? (
          <button
            type="button"
            className="action-button secondary"
            onClick={() => void handleCancel()}
            disabled={cancelling}
          >
            {cancelling ? "Annullamento..." : "Annulla"}
          </button>
        ) : null}
      </div>
      {isRunning && status ? (
        <div className="global-update-meta">
          <span className="pill">{status.current_phase ?? status.status}</span>
          {status.progress_pct !== null && status.progress_pct !== undefined ? (
            <span className="pill">{Math.round(status.progress_pct)}%</span>
          ) : null}
        </div>
      ) : null}
      {status ? (
        <div className="global-update-meta">
          {lastCompletedAt ? (
            <small>
              Ultimo: {formatDateTime(lastCompletedAt)}
              {lastOrigin ? ` (${lastOrigin})` : ""}
            </small>
          ) : null}
          {status.errors.length ? (
            <Link to="/global-update-report" className="action-error-link">
              {status.errors.length} errori
            </Link>
          ) : null}
          {actionError ? <small className="action-error">{actionError}</small> : null}
        </div>
      ) : null}
    </div>
  );
}
