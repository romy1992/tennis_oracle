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
  GlobalUpdateReportRead,
  GlobalUpdateRunRead,
  GlobalUpdateStartResponse,
  ImportFixturesResponse,
  ImportStatusResponse,
  MLModelVersion,
  ModelsVersionsResultsResponse,
  PredictionQueryParams,
  PredictionSummaryResponse,
  RefreshMatchesResponse,
  SingleMatchValueQueryParams,
  SingleMatchValueResponse,
  TelegramBotEventsParams,
  TelegramBotEventsResponse,
  TelegramBotStatsParams,
  TelegramBotStatsResponse,
  TelegramUser,
  TelegramUserInviteCreate,
  TelegramUserListResponse,
  TelegramUsersParams,
  TelegramFeedback,
  TelegramFeedbackListResponse,
  TelegramFeedbackParams,
  TelegramFeedbackStatusUpdate,
  PublishedPrediction,
  PublishedPredictionListResponse,
  PublishedPredictionVersionChainResponse,
  PublishedPredictionsParams,
  PublishedLiveStatsParams,
  PublishedLiveStatsSummary,
  LiveBetaDashboardParams,
  LiveBetaDashboardResponse,
  WeeklyBetaReport,
  WeeklyBetaReportGenerateRequest,
  WeeklyBetaReportGenerateResponse,
  WeeklyBetaReportListResponse,
  WalkForwardRun,
  WalkForwardRunListResponse,
  WalkForwardTriggerRequest,
  WalkForwardTriggerResponse,
  CalibrationRun,
  CalibrationRunListResponse,
  CalibrationTriggerRequest,
  CalibrationTriggerResponse
} from "../types/api";
import { getStoredToken } from "../auth/session";

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000";

export class ApiError extends Error {
  status: number;

  constructor(message: string, status: number) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

type UnauthorizedHandler = () => void;
let unauthorizedHandler: UnauthorizedHandler | null = null;

export function setUnauthorizedHandler(handler: UnauthorizedHandler | null) {
  unauthorizedHandler = handler;
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

function authHeaders(extra?: HeadersInit): HeadersInit {
  const headers = new Headers(extra);
  const token = getStoredToken();
  if (token) {
    headers.set("Authorization", `Bearer ${token}`);
  }
  return headers;
}

async function parseError(response: Response): Promise<ApiError> {
  let message = `HTTP ${response.status}`;
  try {
    const payload = (await response.json()) as { detail?: string | { msg?: string }[] };
    if (typeof payload.detail === "string") {
      message = payload.detail;
    } else if (Array.isArray(payload.detail) && payload.detail[0]?.msg) {
      message = payload.detail[0].msg;
    }
  } catch {
    // Keep the generic HTTP message when the backend does not return JSON.
  }
  if (response.status === 401 && unauthorizedHandler) {
    unauthorizedHandler();
  }
  return new ApiError(message, response.status);
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE_URL}${path}`, {
    ...init,
    headers: authHeaders(init?.headers)
  });
  if (!response.ok) {
    throw await parseError(response);
  }
  if (response.status === 204) {
    return undefined as T;
  }
  return (await response.json()) as T;
}

async function post<T>(path: string, body?: unknown): Promise<T> {
  return request<T>(path, {
    method: "POST",
    headers: body ? { "Content-Type": "application/json" } : undefined,
    body: body ? JSON.stringify(body) : undefined
  });
}

async function patch<T>(path: string, body?: unknown): Promise<T> {
  return request<T>(path, {
    method: "PATCH",
    headers: body ? { "Content-Type": "application/json" } : undefined,
    body: body ? JSON.stringify(body) : undefined
  });
}

export type LoginResponse = {
  access_token: string;
  token_type: string;
  expires_at: string;
};

export type AdminSessionResponse = {
  id: number;
  username: string;
  is_active: boolean;
  authenticated: boolean;
};

export const apiClient = {
  login: (username: string, password: string) =>
    request<LoginResponse>("/api/auth/login", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ username, password })
    }),
  getSession: () => request<AdminSessionResponse>("/api/auth/me"),
  logout: () => post<{ ok: boolean; message: string }>("/api/auth/logout"),
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
  regenerateDailyBettingSlips: (params: BettingSlipsQueryParams = {}) =>
    post<BettingSlipsDailyResponse>(
      withQuery("/api/betting-slips/daily", { ...params, regenerate: true })
    ),
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
  getGlobalUpdateReport: (runId: number) =>
    request<GlobalUpdateReportRead>(`/api/global-update/${runId}/report`),
  getModelsVersionsResults: (params: { date?: string } = {}) =>
    request<ModelsVersionsResultsResponse>(withQuery("/api/models-versions/results", params)),
  getTelegramBotStats: (params: TelegramBotStatsParams = {}) =>
    request<TelegramBotStatsResponse>(withQuery("/api/telegram/stats", params)),
  getTelegramBotEvents: (params: TelegramBotEventsParams = {}) =>
    request<TelegramBotEventsResponse>(withQuery("/api/telegram/events", params)),
  getTelegramUsers: (params: TelegramUsersParams = {}) =>
    request<TelegramUserListResponse>(withQuery("/api/telegram/users", params)),
  inviteTelegramUser: (payload: TelegramUserInviteCreate) =>
    post<TelegramUser>("/api/telegram/users", payload),
  activateTelegramUser: (telegramUserId: number) =>
    post<TelegramUser>(`/api/telegram/users/${telegramUserId}/activate`, {}),
  suspendTelegramUser: (telegramUserId: number) =>
    post<TelegramUser>(`/api/telegram/users/${telegramUserId}/suspend`, {}),
  blockTelegramUser: (telegramUserId: number) =>
    post<TelegramUser>(`/api/telegram/users/${telegramUserId}/block`, {}),
  getTelegramFeedback: (params: TelegramFeedbackParams = {}) =>
    request<TelegramFeedbackListResponse>(withQuery("/api/telegram/feedback", params)),
  updateTelegramFeedbackStatus: (
    feedbackId: number,
    payload: TelegramFeedbackStatusUpdate
  ) => patch<TelegramFeedback>(`/api/telegram/feedback/${feedbackId}`, payload),
  getPublishedPredictions: (params: PublishedPredictionsParams = {}) =>
    request<PublishedPredictionListResponse>(
      withQuery("/api/published-predictions", params)
    ),
  getPublishedPrediction: (id: number) =>
    request<PublishedPrediction>(`/api/published-predictions/${id}`),
  getPublishedPredictionVersions: (publicationId: string) =>
    request<PublishedPredictionVersionChainResponse>(
      `/api/published-predictions/by-publication/${publicationId}`
    ),
  getPublishedLiveStats: (params: PublishedLiveStatsParams = {}) =>
    request<PublishedLiveStatsSummary>(
      withQuery("/api/published-predictions/stats", params)
    ),
  getLiveBetaDashboard: (params: LiveBetaDashboardParams = {}) =>
    request<LiveBetaDashboardResponse>(withQuery("/api/live-beta-dashboard", params)),
  getWeeklyBetaReports: (params: { limit?: number; offset?: number } = {}) =>
    request<WeeklyBetaReportListResponse>(withQuery("/api/weekly-beta-reports", params)),
  getLatestWeeklyBetaReport: () =>
    request<WeeklyBetaReport>("/api/weekly-beta-reports/latest"),
  getWeeklyBetaReport: (reportId: number) =>
    request<WeeklyBetaReport>(`/api/weekly-beta-reports/${reportId}`),
  generateWeeklyBetaReport: (payload: WeeklyBetaReportGenerateRequest = {}) =>
    post<WeeklyBetaReportGenerateResponse>("/api/weekly-beta-reports/generate", payload),
  getWalkForwardRuns: (params: { limit?: number; offset?: number } = {}) =>
    request<WalkForwardRunListResponse>(withQuery("/api/walk-forward", params)),
  getLatestWalkForwardRun: () => request<WalkForwardRun>("/api/walk-forward/latest"),
  getWalkForwardRun: (runId: number) =>
    request<WalkForwardRun>(`/api/walk-forward/runs/${runId}`),
  startWalkForwardRun: (payload: WalkForwardTriggerRequest = {}) =>
    post<WalkForwardTriggerResponse>("/api/walk-forward/runs", payload),
  getCalibrationRuns: (params: { limit?: number; offset?: number } = {}) =>
    request<CalibrationRunListResponse>(withQuery("/api/calibration", params)),
  getLatestCalibrationRun: () => request<CalibrationRun>("/api/calibration/latest"),
  getCalibrationRun: (runId: number) =>
    request<CalibrationRun>(`/api/calibration/runs/${runId}`),
  startCalibrationRun: (payload: CalibrationTriggerRequest = {}) =>
    post<CalibrationTriggerResponse>("/api/calibration/runs", payload)
};
