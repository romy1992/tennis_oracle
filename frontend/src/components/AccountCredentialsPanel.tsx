import { type FormEvent, useState } from "react";

import { useAuth } from "../auth/AuthContext";

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
      <h2 id="account-credentials-title">Credenziali di accesso</h2>
      <p>
        Account attuale: <strong>{username ?? "-"}</strong>. Lascia vuoto ciò che non vuoi cambiare.
      </p>
      <form className="settings-form" onSubmit={(event) => void submit(event)}>
        <label>
          Nuovo username
          <input
            type="text"
            value={newUsername}
            onChange={(event) => setNewUsername(event.target.value)}
            autoComplete="username"
            disabled={busy}
          />
        </label>
        <label>
          Nuova password
          <input
            type="password"
            value={newPassword}
            onChange={(event) => setNewPassword(event.target.value)}
            autoComplete="new-password"
            disabled={busy}
          />
        </label>
        <label>
          Conferma nuova password
          <input
            type="password"
            value={confirmPassword}
            onChange={(event) => setConfirmPassword(event.target.value)}
            autoComplete="new-password"
            disabled={busy}
          />
        </label>
        <label>
          Password attuale
          <input
            type="password"
            value={currentPassword}
            onChange={(event) => setCurrentPassword(event.target.value)}
            autoComplete="current-password"
            placeholder="Conferma la tua identità"
            required
            disabled={busy}
          />
        </label>
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
