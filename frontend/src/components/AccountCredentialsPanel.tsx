import { type FormEvent, useState } from "react";

import { useAuth } from "../auth/AuthContext";
import { apiClient } from "../services/apiClient";
import { SecretField } from "./SecretField";

const MIN_PASSWORD_LENGTH = 8;

export function AccountCredentialsPanel() {
  const { username, updateCredentials } = useAuth();
  const [currentPassword, setCurrentPassword] = useState("");
  const [newUsername, setNewUsername] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);

  async function submit(event: FormEvent) {
    event.preventDefault();
    setError(null);
    setMessage(null);
    const wantedUsername = newUsername.trim();
    const changesUsername = wantedUsername !== "" && wantedUsername !== username;
    const changesPassword = newPassword !== "";
    if (!changesUsername && !changesPassword) {
      setError("Inserisci un nuovo username e/o una nuova password.");
      return;
    }
    if (changesPassword && newPassword.length < MIN_PASSWORD_LENGTH) {
      setError(`La nuova password deve avere almeno ${MIN_PASSWORD_LENGTH} caratteri.`);
      return;
    }
    if (changesPassword && newPassword !== confirmPassword) {
      setError("Le due password non coincidono.");
      return;
    }
    setBusy(true);
    try {
      await updateCredentials(
        currentPassword,
        changesUsername ? wantedUsername : undefined,
        changesPassword ? newPassword : undefined
      );
      setCurrentPassword("");
      setNewUsername("");
      setNewPassword("");
      setConfirmPassword("");
      setMessage("Credenziali aggiornate.");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Operazione non riuscita.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="panel settings-provider-panel" aria-labelledby="account-credentials-title">
      <div className="settings-provider-header">
        <div>
          <span className="settings-eyebrow">Accesso al portale</span>
          <h3 id="account-credentials-title">Credenziali di accesso</h3>
        </div>
      </div>
      <div className="settings-secret-form">
        <label>
          Username attuale
          <span className="cred-field-row cred-field-pad">
            <input type="text" value={username ?? ""} readOnly />
          </span>
        </label>
        <SecretField
          label="Password salvata"
          key={message ?? "initial"}
          onReveal={async () => (await apiClient.revealCredentials()).password}
        />
      </div>
      <form className="settings-secret-form" onSubmit={(event) => void submit(event)}>
        <p className="note" style={{ gridColumn: "1 / -1", margin: 0 }}>
          Lascia vuoto ciò che non vuoi cambiare.
        </p>
        <label>
          Nuovo username
          <span className="cred-field-row cred-field-pad">
            <input
              type="text"
              value={newUsername}
              onChange={(event) => setNewUsername(event.target.value)}
              autoComplete="username"
              disabled={busy}
            />
          </span>
        </label>
        <SecretField label="Nuova password" value={newPassword} onChange={setNewPassword} autoComplete="new-password" disabled={busy} />
        <SecretField label="Conferma nuova password" value={confirmPassword} onChange={setConfirmPassword} autoComplete="new-password" disabled={busy} />
        <SecretField label="Password attuale" value={currentPassword} onChange={setCurrentPassword} autoComplete="current-password" required disabled={busy} />
        <div className="settings-form-actions">
          <button type="submit" className="action-button primary" disabled={busy}>
            Aggiorna credenziali
          </button>
        </div>
      </form>
      {message ? (
        <div className="settings-alert success" role="status">
          {message}
        </div>
      ) : null}
      {error ? (
        <div className="settings-alert error" role="alert">
          {error}
        </div>
      ) : null}
    </section>
  );
}
