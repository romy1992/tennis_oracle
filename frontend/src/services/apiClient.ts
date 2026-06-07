import type { BackendHealth, ListParams, Player, TennisMatch, Tournament } from "../types/api";

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000";

export class ApiError extends Error {
  status: number;

  constructor(message: string, status: number) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

function withQuery(path: string, params: Record<string, string | number | undefined> = {}) {
  const search = new URLSearchParams();
  Object.entries(params).forEach(([key, value]) => {
    if (value !== undefined) {
      search.set(key, String(value));
    }
  });
  const query = search.toString();
  return `${path}${query ? `?${query}` : ""}`;
}

async function request<T>(path: string): Promise<T> {
  const response = await fetch(`${API_BASE_URL}${path}`);
  if (!response.ok) {
    let message = `HTTP ${response.status}`;
    try {
      const payload = (await response.json()) as { detail?: string };
      message = payload.detail ?? message;
    } catch {
      // Keep the generic HTTP message when the backend does not return JSON.
    }
    throw new ApiError(message, response.status);
  }
  return (await response.json()) as T;
}

export const apiClient = {
  getHealth: () => request<BackendHealth>("/health"),
  getMatches: (params: ListParams = {}) =>
    request<TennisMatch[]>(withQuery("/api/matches", params)),
  getMatch: (matchId: number) => request<TennisMatch>(`/api/matches/${matchId}`),
  getPlayers: (params: ListParams = {}) =>
    request<Player[]>(withQuery("/api/players", params)),
  getPlayer: (playerId: number) => request<Player>(`/api/players/${playerId}`),
  getTournaments: (params: ListParams = {}) =>
    request<Tournament[]>(withQuery("/api/tournaments", params))
};
