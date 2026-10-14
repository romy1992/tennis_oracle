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
  const { status, isRunning, triggerUpdate, forceSlips, cancelUpdate, lastCompletedAt, lastOrigin } =
    useGlobalUpdate();
  const [actionError, setActionError] = useState<string | null>(null);
  const [actionInfo, setActionInfo] = useState<string | null>(null);
  const [cancelling, setCancelling] = useState(false);
  const [outsideHoursWarning, setOutsideHoursWarning] = useState<string | null>(null);
  const [forcing, setForcing] = useState(false);
  // Conferma di forzare le schedine data mentre l'aggiornamento e' ancora in corso: si esegue a fine run.
  const [forceAfterRun, setForceAfterRun] = useState(false);
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

  function errorText(err: unknown, fallback: string) {
    return err instanceof ApiError ? err.message : err instanceof Error ? err.message : fallback;
  }

  async function runForceSlips() {
    try {
      setActionError(null);
      setForcing(true);
      const result = await forceSlips();
      setActionInfo(result.message);
    } catch (err) {
      setActionError(errorText(err, "Errore durante la forzatura delle schedine."));
    } finally {
      setForcing(false);
    }
  }

  useEffect(() => {
    if (forceAfterRun && !isRunning) {
      setForceAfterRun(false);
      void runForceSlips();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [forceAfterRun, isRunning]);

  async function handleClick() {
    try {
      setActionError(null);
      setActionInfo(null);
      // L'aggiornamento parte sempre; dopo la chiusura del pool le schedine restano ferme
      // e il pop-up chiede se forzarle.
      const started = await triggerUpdate(true);
      if (started.slips_closed) {
        setOutsideHoursWarning(
          `Aggiornamento partite avviato. Il pool schedine di oggi è chiuso dalle ${
            started.slips_close_time ?? "10:00"
          }: le schedine non sono state modificate.`
        );
      }
    } catch (err) {
      setActionError(errorText(err, "Errore durante l'aggiornamento globale."));
    }
  }

  function handleOpenForceSlips() {
    setActionError(null);
    setActionInfo(null);
    setOutsideHoursWarning("Le schedine di oggi sono chiuse dopo la scadenza del pool.");
  }

  async function handleForceOutsideHours() {
    setOutsideHoursWarning(null);
    if (isRunning) {
      setForceAfterRun(true);
      setActionInfo("Le schedine verranno forzate al termine dell'aggiornamento in corso.");
      return;
    }
    await runForceSlips();
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
        <button
          type="button"
          className="action-button secondary"
          onClick={handleOpenForceSlips}
          disabled={forcing || forceAfterRun}
        >
          {forcing ? "Forzo le schedine..." : "Forza schedine"}
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
          {actionInfo ? <small>{actionInfo}</small> : null}
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
                <li>solo le schedine vengono rigenerate (l'aggiornamento delle partite non cambia);</li>
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
                Non forzare
              </button>
              <button
                type="button"
                className="action-button primary"
                onClick={() => void handleForceOutsideHours()}
                disabled={forcing}
              >
                Forza
              </button>
            </div>
          </div>
        </div>
      ) : null}
    </div>
  );
}
