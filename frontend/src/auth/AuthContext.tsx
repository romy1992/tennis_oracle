import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode
} from "react";

import { apiClient, ApiError, setUnauthorizedHandler } from "../services/apiClient";
import {
  clearSession,
  getStoredExpiresAt,
  getStoredToken,
  isTokenExpired,
  storeSession
} from "./session";

type AuthState = {
  token: string | null;
  username: string | null;
  loading: boolean;
  login: (username: string, password: string) => Promise<void>;
  logout: () => Promise<void>;
  isAuthenticated: boolean;
};

const AuthContext = createContext<AuthState | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [token, setToken] = useState<string | null>(() => {
    const stored = getStoredToken();
    if (!stored || isTokenExpired()) {
      clearSession();
      return null;
    }
    return stored;
  });
  const [username, setUsername] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  const logout = useCallback(async () => {
    try {
      if (getStoredToken()) {
        await apiClient.logout();
      }
    } catch {
      // Client-side logout always clears local session.
    } finally {
      clearSession();
      setToken(null);
      setUsername(null);
    }
  }, []);

  useEffect(() => {
    setUnauthorizedHandler(() => {
      clearSession();
      setToken(null);
      setUsername(null);
    });
    return () => setUnauthorizedHandler(null);
  }, []);

  useEffect(() => {
    let cancelled = false;

    async function restore() {
      const stored = getStoredToken();
      if (!stored || isTokenExpired(getStoredExpiresAt())) {
        clearSession();
        if (!cancelled) {
          setToken(null);
          setUsername(null);
          setLoading(false);
        }
        return;
      }
      try {
        const session = await apiClient.getSession();
        if (!cancelled) {
          setToken(stored);
          setUsername(session.username);
        }
      } catch (error) {
        if (error instanceof ApiError && (error.status === 401 || error.status === 403)) {
          clearSession();
          if (!cancelled) {
            setToken(null);
            setUsername(null);
          }
        }
      } finally {
        if (!cancelled) {
          setLoading(false);
        }
      }
    }

    void restore();
    return () => {
      cancelled = true;
    };
  }, []);

  const login = useCallback(async (loginUsername: string, password: string) => {
    const result = await apiClient.login(loginUsername, password);
    storeSession(result.access_token, result.expires_at);
    setToken(result.access_token);
    const session = await apiClient.getSession();
    setUsername(session.username);
  }, []);

  const value = useMemo<AuthState>(
    () => ({
      token,
      username,
      loading,
      login,
      logout,
      isAuthenticated: Boolean(token)
    }),
    [token, username, loading, login, logout]
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthState {
  const ctx = useContext(AuthContext);
  if (!ctx) {
    throw new Error("useAuth must be used within AuthProvider");
  }
  return ctx;
}
