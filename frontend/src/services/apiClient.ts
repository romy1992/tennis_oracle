import type {
  BettingSlipCalendarResponse,
  BettingSlipModelStatsParams,
  BettingSlipModelStatsResponse,
  BettingSlipStatsParams,
  BettingSlipStatsResponse,
  BettingSlipsDailyResponse,
  BettingSlipsQueryParams,
  BettingSlipsRefreshResponse,
  DailyPredictionStatsResponse,
  DailyStatsParams,
  FixturesWithPredictionsPage,
  GlobalUpdateRunRead,
  GlobalUpdateStartResponse,
  ImportFixturesResponse,
  ImportStatusResponse,
  MLModelVersion,
  ModelsVersionsResultsResponse,
  NextFixtureWithPrediction,
  PredictionQueryParams,
  PredictionSummaryResponse,
  RefreshMatchesResponse,
  SingleMatchValueQueryParams,
  SingleMatchValueResponse
} from "../types/api";

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000";

export class ApiError extends Error {
  status: number;

  constructor(message: string, status: number) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

function withQuery(
  path: string,
  params: Record<string, string | number | boolean | undefined> = {}
) {
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

async function post<T>(path: string, body?: unknown): Promise<T> {
  const response = await fetch(`${API_BASE_URL}${path}`, {
    method: "POST",
    headers: body ? { "Content-Type": "application/json" } : undefined,
    body: body ? JSON.stringify(body) : undefined
  });
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
  getNextFixturesPredictions: (params: PredictionQueryParams = {}) =>
    request<FixturesWithPredictionsPage>(
      withQuery("/api/next-fixtures/predictions", params)
    ),
  getUpcomingPredictions: (params: PredictionQueryParams = {}) =>
    request<FixturesWithPredictionsPage>(
      withQuery("/api/next-fixtures/predictions", params)
    ),
  getDailyPredictionStats: (params: DailyStatsParams = {}) =>
    request<DailyPredictionStatsResponse>(
      withQuery("/api/predictions/stats/daily", params)
    ),
  getPredictionSummary: (params: { model_version?: MLModelVersion; model_name?: string } = {}) =>
    request<PredictionSummaryResponse>(
      withQuery("/api/predictions/stats/summary", params)
    ),
  getSingleMatchValueAnalysis: (params: SingleMatchValueQueryParams = {}) =>
    request<SingleMatchValueResponse>(
      withQuery("/api/single-match-value", params)
    ),
  getImportStatus: () => request<ImportStatusResponse>("/api/imports/status"),
  refreshMatches: (params: {
    model_version?: MLModelVersion;
    model_name?: string;
    force_next_import?: boolean;
  } = {}) =>
    post<RefreshMatchesResponse>(
      withQuery("/api/imports/refresh", params)
    ),
  importPlayedFixtures: (daysBack: number) =>
    post<ImportFixturesResponse>("/api/imports/fixtures", { days_back: daysBack }),
  getDailyBettingSlips: (params: BettingSlipsQueryParams = {}) =>
    request<BettingSlipsDailyResponse>(withQuery("/api/betting-slips/daily", params)),
  refreshBettingSlips: (params: BettingSlipsQueryParams = {}) =>
    post<BettingSlipsRefreshResponse>(withQuery("/api/betting-slips/refresh", params)),
  getBettingSlipStats: (params: BettingSlipStatsParams = {}) =>
    request<BettingSlipStatsResponse>(withQuery("/api/betting-slips/stats", params)),
  getBettingSlipModelStats: (params: BettingSlipModelStatsParams = {}) =>
    request<BettingSlipModelStatsResponse>(
      withQuery("/api/betting-slips/stats/by-model", params)
    ),
  getBettingSlipCalendar: (params: { model_version?: MLModelVersion; model_name?: string } = {}) =>
    request<BettingSlipCalendarResponse>(withQuery("/api/betting-slips/calendar", params)),
  startGlobalUpdate: (params: { force?: boolean; days_forward?: number; days_back_fixtures?: number } = {}) =>
    post<GlobalUpdateStartResponse>("/api/global-update", params),
  getGlobalUpdateStatus: () => request<GlobalUpdateRunRead | null>("/api/global-update/status"),
  getGlobalUpdateLatest: () => request<GlobalUpdateRunRead | null>("/api/global-update/latest"),
  cancelGlobalUpdate: (runId: number) =>
    post<GlobalUpdateStartResponse>(`/api/global-update/${runId}/cancel`, {}),
  getGlobalUpdateRun: (runId: number) =>
    request<GlobalUpdateRunRead>(`/api/global-update/${runId}`),
  getModelsVersionsResults: (params: { date?: string } = {}) =>
    request<ModelsVersionsResultsResponse>(withQuery("/api/models-versions/results", params))
};
