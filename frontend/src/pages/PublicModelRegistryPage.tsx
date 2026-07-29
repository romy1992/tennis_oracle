import { FormEvent, useCallback, useEffect, useState } from "react";

import { EmptyState, ErrorState, LoadingState } from "../components/Status";
import { apiClient, ApiError } from "../services/apiClient";
import type {
  MLModelName,
  MLModelVersion,
  PublicModelRegistryEntry,
  PublicModelRegistryListResponse
} from "../types/api";
import { MODEL_NAMES, MODEL_VERSIONS } from "../utils/modelVersion";

function formatDateTime(value: string | null | undefined) {
  if (!value) return "-";
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return value;
  return parsed.toLocaleString("it-IT");
}

function statusLabel(status: string) {
  switch (status) {
    case "active":
      return "Attivo";
    case "candidate":
      return "Candidato";
    case "retired":
      return "Ritirato";
    default:
      return status;
  }
}

export function PublicModelRegistryPage() {
  const [data, setData] = useState<PublicModelRegistryListResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [actionMessage, setActionMessage] = useState<string | null>(null);
  const [modelVersion, setModelVersion] = useState<MLModelVersion>("v3");
  const [modelName, setModelName] = useState<MLModelName>(
    MODEL_NAMES[0]?.value ?? "logistic_regression"
  );
  const [candidateMotivation, setCandidateMotivation] = useState("");
  const [rollbackMotivation, setRollbackMotivation] = useState("");
  const [submitting, setSubmitting] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const response = await apiClient.getPublicModelRegistry({ limit: 100 });
      setData(response);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Errore caricamento registro modello");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  async function handleCreateCandidate(event: FormEvent) {
    event.preventDefault();
    setSubmitting(true);
    setActionError(null);
    setActionMessage(null);
    try {
      await apiClient.createPublicModelCandidate({
        model_version: modelVersion,
        model_name: modelName,
        motivation: candidateMotivation.trim() || null
      });
      setCandidateMotivation("");
      setActionMessage("Candidato registrato.");
      await load();
    } catch (err) {
      setActionError(err instanceof ApiError ? err.message : "Registrazione candidato fallita");
    } finally {
      setSubmitting(false);
    }
  }

  async function handleActivate(entry: PublicModelRegistryEntry) {
    const motivation = window.prompt(
      "Motivazione attivazione (obbligatoria):",
      entry.motivation ?? ""
    );
    if (!motivation?.trim()) return;
    setSubmitting(true);
    setActionError(null);
    setActionMessage(null);
    try {
      const response = await apiClient.activatePublicModelEntry(entry.id, motivation.trim());
      setActionMessage(response.message);
      await load();
    } catch (err) {
      setActionError(err instanceof ApiError ? err.message : "Attivazione fallita");
    } finally {
      setSubmitting(false);
    }
  }

  async function handleRollback() {
    if (!rollbackMotivation.trim()) {
      setActionError("Inserisci una motivazione per il rollback.");
      return;
    }
    setSubmitting(true);
    setActionError(null);
    setActionMessage(null);
    try {
      const response = await apiClient.rollbackPublicModel(rollbackMotivation.trim());
      setRollbackMotivation("");
      setActionMessage(response.message);
      await load();
    } catch (err) {
      setActionError(err instanceof ApiError ? err.message : "Rollback fallito");
    } finally {
      setSubmitting(false);
    }
  }

  if (loading) return <LoadingState title="Caricamento registro modello pubblico..." />;
  if (error) return <ErrorState title="Errore registro modello" message={error} />;
  if (!data) return <EmptyState title="Registro non disponibile" message="Nessun dato." />;

  return (
    <div className="page-stack">
      <header className="page-header">
        <h2>Registro modello pubblico (ML-07)</h2>
        <p>
          Modello ufficiale per pubblicazione live e bot Telegram. Le pubblicazioni già
          salvate non vengono modificate retroattivamente.
        </p>
      </header>

      {actionMessage ? <p className="success-banner">{actionMessage}</p> : null}
      {actionError ? <p className="error-banner">{actionError}</p> : null}

      <section className="panel">
        <h3>Modello attivo</h3>
        {data.active ? (
          <dl className="detail-grid">
            <div>
              <dt>Combinazione</dt>
              <dd>
                {data.active.model_version} / {data.active.model_name}
              </dd>
            </div>
            <div>
              <dt>Attivato il</dt>
              <dd>{formatDateTime(data.active.activated_at)}</dd>
            </div>
            <div>
              <dt>Motivazione</dt>
              <dd>{data.active.motivation ?? "-"}</dd>
            </div>
            <div>
              <dt>Artefatto</dt>
              <dd>{data.active.artifacts.model_pkl ?? "-"}</dd>
            </div>
          </dl>
        ) : (
          <EmptyState
            title="Nessun modello attivo"
            message="Registra e attiva un candidato oppure usa il fallback env PUBLIC_MODEL_*."
          />
        )}
      </section>

      <section className="panel">
        <h3>Registra candidato</h3>
        <form className="inline-form" onSubmit={(event) => void handleCreateCandidate(event)}>
          <label>
            Versione
            <select
              value={modelVersion}
              onChange={(event) => setModelVersion(event.target.value as MLModelVersion)}
            >
              {MODEL_VERSIONS.map((item) => (
                <option key={item.value} value={item.value}>
                  {item.label}
                </option>
              ))}
            </select>
          </label>
          <label>
            Modello
            <select
              value={modelName}
              onChange={(event) => setModelName(event.target.value as MLModelName)}
            >
              {MODEL_NAMES.map((item) => (
                <option key={item.value} value={item.value}>
                  {item.label}
                </option>
              ))}
            </select>
          </label>
          <label>
            Motivazione
            <input
              type="text"
              value={candidateMotivation}
              onChange={(event) => setCandidateMotivation(event.target.value)}
              placeholder="Es. miglior holdout su v3"
            />
          </label>
          <button type="submit" className="action-button" disabled={submitting}>
            Aggiungi candidato
          </button>
        </form>
      </section>

      <section className="panel">
        <h3>Rollback</h3>
        <p>Ripristina il modello precedente sostituito dall&apos;attuale attivo.</p>
        <div className="inline-form">
          <label>
            Motivazione rollback
            <input
              type="text"
              value={rollbackMotivation}
              onChange={(event) => setRollbackMotivation(event.target.value)}
              placeholder="Es. regressione live osservata"
            />
          </label>
          <button
            type="button"
            className="action-button secondary"
            disabled={submitting || !data.active?.supersedes_entry_id}
            onClick={() => void handleRollback()}
          >
            Esegui rollback
          </button>
        </div>
      </section>

      <section className="panel">
        <h3>Storico registro</h3>
        {data.items.length === 0 ? (
          <EmptyState title="Storico vuoto" message="Nessuna voce nel registro." />
        ) : (
          <div className="table-scroll">
            <table>
              <thead>
                <tr>
                  <th>ID</th>
                  <th>Versione / modello</th>
                  <th>Stato</th>
                  <th>Attivazione</th>
                  <th>Motivazione</th>
                  <th>Azioni</th>
                </tr>
              </thead>
              <tbody>
                {data.items.map((entry) => (
                  <tr key={entry.id}>
                    <td>{entry.id}</td>
                    <td>
                      {entry.model_version} / {entry.model_name}
                    </td>
                    <td>{statusLabel(entry.status)}</td>
                    <td>{formatDateTime(entry.activated_at)}</td>
                    <td>{entry.motivation ?? "-"}</td>
                    <td>
                      {entry.status === "candidate" ? (
                        <button
                          type="button"
                          className="action-button"
                          disabled={submitting}
                          onClick={() => void handleActivate(entry)}
                        >
                          Attiva
                        </button>
                      ) : (
                        "-"
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </div>
  );
}
