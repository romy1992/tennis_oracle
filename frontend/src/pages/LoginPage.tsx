import { type FormEvent, useState } from "react";
import { Navigate, useLocation } from "react-router-dom";

import { useAuth } from "../auth/AuthContext";
import { ApiError } from "../services/apiClient";

export function LoginPage() {
  const { login, isAuthenticated, loading } = useAuth();
  const location = useLocation();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  if (!loading && isAuthenticated) {
    const redirectTo = (location.state as { from?: string } | null)?.from ?? "/predictions";
    return <Navigate to={redirectTo} replace />;
  }

  async function onSubmit(event: FormEvent) {
    event.preventDefault();
    setError(null);
    setSubmitting(true);
    try {
      await login(username.trim(), password);
    } catch (err) {
      if (err instanceof ApiError) {
        setError(err.message);
      } else {
        setError("Login non riuscito.");
      }
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="login-page">
      <form className="login-card" onSubmit={onSubmit}>
        <h1>tennis_oracle</h1>
        <p>Accedi con l&apos;account amministratore.</p>
        <label>
          Username
          <input
            autoComplete="username"
            value={username}
            onChange={(e) => setUsername(e.target.value)}
            required
          />
        </label>
        <label>
          Password
          <input
            type="password"
            autoComplete="current-password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            required
          />
        </label>
        {error ? <div className="login-error">{error}</div> : null}
        <button className="action-button primary" type="submit" disabled={submitting}>
          {submitting ? "Accesso…" : "Accedi"}
        </button>
      </form>
    </div>
  );
}
