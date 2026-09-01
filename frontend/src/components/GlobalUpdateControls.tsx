import { useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";

import { useGlobalUpdate } from "../hooks/useGlobalUpdate";
import { ApiError } from "../services/apiClient";
import { ACTIVE_MARKETS } from "../utils/modelVersion";

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
  const [outsideHoursWarning, setOutsideHoursWarning] = useState<string | null>(null);
  const [forcing, setForcing] = useState(false);
  const cancelButtonRef = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    if (!outsideHoursWarning) return;
    cancelButtonRef.current?.focus();
    function handleEscape(event: KeyboardEvent) {
      if (event.key === "Escape" && !forcing) setOutsideHoursWarning(null);
    }
    window.addEventListener("keydown", handleEscape);
    return () => window.removeEventListener("keydown", handleEscape);
  }, [forcing, outsideHoursWarning]);

  async function handleClick() {
    try {
      setActionError(null);
      await triggerUpdate(true);
    } catch (err) {
      if (err instanceof ApiError && err.status === 423) {
        setOutsideHoursWarning(err.message);
        return;
      }
      const message =
        err instanceof ApiError
          ? err.message
          : err instanceof Error
            ? err.message
            : "Errore durante l'aggiornamento globale.";
      setActionError(message);
    }
  }

  async function handleForceOutsideHours() {
    try {
      setActionError(null);
      setForcing(true);
      await triggerUpdate(true, undefined, true);
      setOutsideHoursWarning(null);
    } catch (err) {
      const message =
        err instanceof ApiError
          ? err.message
          : err instanceof Error
            ? err.message
            : "Errore durante l'aggiornamento globale forzato.";
      setActionError(message);
      setOutsideHoursWarning(null);
    } finally {
      setForcing(false);
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
      <div className="global-update-version-filters" aria-label="Mercati coperti">
        <small className="global-update-markets-note">
          Copre sempre tutti i mercati: {ACTIVE_MARKETS.map((option) => option.label).join(", ")}.
        </small>
      </div>
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
      {outsideHoursWarning ? (
        <div className="global-update-modal-backdrop" role="presentation">
          <div
            className="global-update-modal"
            role="dialog"
            aria-modal="true"
            aria-labelledby="global-update-outside-hours-title"
            aria-describedby="global-update-outside-hours-description"
          >
            <h2 id="global-update-outside-hours-title">Aggiornamento fuori orario</h2>
            <div id="global-update-outside-hours-description">
              <p>{outsideHoursWarning}</p>
              <p>
                Se scegli <strong>Forza</strong>:
              </p>
              <ul>
                <li>la pipeline globale viene avviata comunque;</li>
                <li>il pool schedine di oggi può ricevere nuove pick anche dopo la chiusura;</li>
                <li>il risultato giornaliero può differire da quello congelato all'orario limite.</li>
              </ul>
              <p>Le giornate storiche e le partite già iniziate restano protette.</p>
            </div>
            <div className="global-update-modal-actions">
              <button
                ref={cancelButtonRef}
                type="button"
                className="action-button secondary"
                onClick={() => setOutsideHoursWarning(null)}
                disabled={forcing}
              >
                Annulla
              </button>
              <button
                type="button"
                className="action-button primary"
                onClick={() => void handleForceOutsideHours()}
                disabled={forcing}
              >
                {forcing ? "Avvio..." : "Forza"}
              </button>
            </div>
          </div>
        </div>
      ) : null}
    </div>
  );
}
