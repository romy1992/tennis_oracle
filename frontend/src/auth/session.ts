const TOKEN_KEY = "tennis_oracle_admin_token";
const EXPIRES_KEY = "tennis_oracle_admin_expires_at";

export function getStoredToken(): string | null {
  return localStorage.getItem(TOKEN_KEY);
}

export function getStoredExpiresAt(): string | null {
  return localStorage.getItem(EXPIRES_KEY);
}

export function storeSession(accessToken: string, expiresAt: string) {
  localStorage.setItem(TOKEN_KEY, accessToken);
  localStorage.setItem(EXPIRES_KEY, expiresAt);
}

export function clearSession() {
  localStorage.removeItem(TOKEN_KEY);
  localStorage.removeItem(EXPIRES_KEY);
}

export function isTokenExpired(expiresAt: string | null = getStoredExpiresAt()): boolean {
  if (!expiresAt) {
    return true;
  }
  const ms = Date.parse(expiresAt);
  if (Number.isNaN(ms)) {
    return true;
  }
  return Date.now() >= ms;
}
