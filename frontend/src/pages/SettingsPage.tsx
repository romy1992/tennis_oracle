import { type FormEvent, useEffect, useState } from "react";

import { ErrorState, LoadingState } from "../components/Status";
import { ScheduledJobsPanel } from "../components/ScheduledJobsPanel";
import { ApiError, apiClient } from "../services/apiClient";
import type { ApiTennisProviderSettings } from "../types/api";


type ConfirmationMode = "verified" | "force" | null;

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : "Operazione non riuscita.";
}

function sourceLabel(source: ApiTennisProviderSettings["source"]): string {
  if (source === "database") return "Override nel database";
  if (source === "environment") return "Variabile d'ambiente";
  return "Non configurata";
}

function formatDateTime(value: string | null): string {
  if (!value) return "-";
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return value;
  return parsed.toLocaleString("it-IT", {
    dateStyle: "short",
    timeStyle: "medium"
  });
}

export function SettingsPage() {
  const [settings, setSettings] = useState<ApiTennisProviderSettings | null>(null);
  const [apiKey, setApiKey] = useState("");
  const [adminPassword, setAdminPassword] = useState("");
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [actionMessage, setActionMessage] = useState<string | null>(null);
  const [canForce, setCanForce] = useState(false);
  const [confirmation, setConfirmation] = useState<ConfirmationMode>(null);

  const loadSettings = async () => {
    setLoading(true);
    setLoadError(null);
    try {
      setSettings(await apiClient.getApiTennisSettings());
    } catch (error) {
      setLoadError(errorMessage(error));
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    void loadSettings();
  }, []);

  const testConnection = async () => {
    setBusy(true);
    setActionError(null);
    setActionMessage(null);
    try {
      const response = await apiClient.testApiTennisConnection(
        apiKey.trim() ? { api_key: apiKey.trim() } : {}
      );
      setActionMessage(response.message);
      setCanForce(false);
    } catch (error) {
      setActionError(errorMessage(error));
    } finally {
      setBusy(false);
    }
  };

  const requestSave = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setActionError(null);
    setActionMessage(null);
    if (!apiKey.trim() || !adminPassword) {
      setActionError("Inserisci la nuova chiave e la password amministratore.");
      return;
    }
    setConfirmation("verified");
  };

  const saveKey = async (verifyBeforeSave: boolean) => {
    setConfirmation(null);
    setBusy(true);
    setActionError(null);
    setActionMessage(null);
    try {
      const response = await apiClient.updateApiTennisKey({
        api_key: apiKey.trim(),
        admin_password: adminPassword,
        verify_before_save: verifyBeforeSave
      });
      setSettings(response.settings);
      setApiKey("");
      setAdminPassword("");
      setCanForce(false);
      setActionMessage(response.message);
    } catch (error) {
      setActionError(errorMessage(error));
      setCanForce(
        verifyBeforeSave && error instanceof ApiError && error.status === 422
      );
    } finally {
      setBusy(false);
    }
  };

  if (loading) {
    return <LoadingState title="Caricamento impostazioni..." />;
  }

  if (loadError || !settings) {
    return (
      <div className="page">
        <ErrorState
          title="Impostazioni non disponibili"
          message={loadError || "Configurazione provider non disponibile."}
        />
        <div>
          <button
            type="button"
            className="action-button"
            onClick={() => void loadSettings()}
          >
            Riprova
          </button>
        </div>
      </div>
    );
  }

  return (
    <div className="page settings-page">
      <header className="page-header">
        <div>
          <h2>Impostazioni</h2>
          <p>Gestisci le integrazioni e i job automatici usati dai processi di aggiornamento.</p>
        </div>
      </header>

      <section className="panel settings-provider-panel">
        <div className="settings-provider-header">
          <div>
            <span className="settings-eyebrow">Provider dati tennis</span>
            <h3>API-Tennis</h3>
            <p className="note">
              La chiave attuale non viene mai inviata al browser. Il fingerprint serve
              soltanto a riconoscere quale configurazione è attiva.
            </p>
          </div>
          <span className={`settings-status ${settings.usable ? "ready" : "blocked"}`}>
            {settings.usable ? "Operativa" : "Non operativa"}
          </span>
        </div>

        <dl className="settings-detail-grid">
          <div>
            <dt>Ambiente</dt>
            <dd>{settings.environment}</dd>
          </div>
          <div>
            <dt>Sorgente attiva</dt>
            <dd>{sourceLabel(settings.source)}</dd>
          </div>
          <div>
            <dt>Fingerprint</dt>
            <dd>{settings.fingerprint || "-"}</dd>
          </div>
          <div>
            <dt>Ultimo aggiornamento</dt>
            <dd>{formatDateTime(settings.updated_at)}</dd>
          </div>
          <div>
            <dt>Aggiornata da</dt>
            <dd>{settings.updated_by || "-"}</dd>
          </div>
          <div>
            <dt>Timeout</dt>
            <dd>{settings.timeout_seconds} secondi</dd>
          </div>
          <div className="settings-detail-wide">
            <dt>Endpoint</dt>
            <dd>{settings.base_url || "Non configurato"}</dd>
          </div>
        </dl>

        {settings.warning ? (
          <div className="settings-alert warning" role="alert">
            {settings.warning}
          </div>
        ) : null}

        <form className="settings-secret-form" onSubmit={requestSave}>
          <label>
            Nuova chiave API
            <input
              type="password"
              value={apiKey}
              onChange={(event) => {
                setApiKey(event.target.value);
                setCanForce(false);
              }}
              autoComplete="off"
              spellCheck={false}
              placeholder="Incolla la nuova chiave"
              disabled={busy}
            />
          </label>
          <label>
            Password amministratore
            <input
              type="password"
              value={adminPassword}
              onChange={(event) => setAdminPassword(event.target.value)}
              autoComplete="current-password"
              placeholder="Conferma la tua identità"
              disabled={busy}
            />
          </label>

          <div className="settings-form-actions">
            <button
              type="button"
              className="action-button"
              onClick={() => void testConnection()}
              disabled={busy || (!apiKey.trim() && !settings.usable)}
            >
              {apiKey.trim() ? "Verifica nuova chiave" : "Verifica connessione attiva"}
            </button>
            <button
              type="submit"
              className="action-button primary"
              disabled={busy}
            >
              Salva e attiva
            </button>
            {canForce ? (
              <button
                type="button"
                className="action-button danger"
                onClick={() => setConfirmation("force")}
                disabled={busy}
              >
                Salva senza verifica
              </button>
            ) : null}
          </div>
        </form>

        {actionMessage ? (
          <div className="settings-alert success" role="status">
            {actionMessage}
          </div>
        ) : null}
        {actionError ? (
          <div className="settings-alert error" role="alert">
            {actionError}
          </div>
        ) : null}
      </section>

      <ScheduledJobsPanel />

      {confirmation ? (
        <div className="global-update-modal-backdrop" role="presentation">
          <div
            className="global-update-modal"
            role="dialog"
            aria-modal="true"
            aria-labelledby="provider-key-confirm-title"
          >
            <h2 id="provider-key-confirm-title">
              {confirmation === "force"
                ? "Attivare una chiave non verificata?"
                : "Sostituire la chiave API-Tennis?"}
            </h2>
            <p>
              {confirmation === "force"
                ? "La verifica con il provider è fallita. Forzando il salvataggio, import e aggiornamenti potrebbero interrompersi immediatamente."
                : "La nuova chiave verrà verificata con il provider e, se valida, diventerà subito attiva per API e job di aggiornamento."}
            </p>
            <div className="global-update-modal-actions">
              <button
                type="button"
                className="action-button"
                onClick={() => setConfirmation(null)}
              >
                Annulla
              </button>
              <button
                type="button"
                className={`action-button ${confirmation === "force" ? "danger" : "primary"}`}
                onClick={() => void saveKey(confirmation !== "force")}
              >
                {confirmation === "force" ? "Forza" : "Verifica e attiva"}
              </button>
            </div>
          </div>
        </div>
      ) : null}
    </div>
  );
}
