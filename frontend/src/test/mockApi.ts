import { vi, type Mock } from "vitest";

import {
  emptyValueAnalysis,
  idleGlobalUpdate,
  importStatus,
  makeCalendar,
  makeDailySlips,
  makeFixturesPage,
  makeSlipStats,
  modelsCatalog,
  telegramEvents,
  telegramStats,
  publishedPredictions,
  publishedLiveStats,
  liveBetaDashboard
} from "./fixtures";

export type ApiMocks = Record<string, Mock>;

/** Default happy-path stubs shared across page/app tests. */
export function stubDefaultApi(apiMocks: {
  getSession: Mock;
  login: Mock;
  logout: Mock;
  getGlobalUpdateStatus: Mock;
  startGlobalUpdate: Mock;
  cancelGlobalUpdate: Mock;
  getGlobalUpdateLatest: Mock;
  getModelsVersionsResults: Mock;
  getUpcomingPredictions: Mock;
  getNextFixturesPredictions: Mock;
  getSingleMatchValueAnalysis: Mock;
  getImportStatus: Mock;
  getBettingSlipCalendar: Mock;
  getDailyBettingSlips: Mock;
  regenerateDailyBettingSlips: Mock;
  getBettingSlipStats: Mock;
  getTelegramBotStats: Mock;
  getTelegramBotEvents: Mock;
  getPredictionSummary: Mock;
  getDailyPredictionStats: Mock;
  getBettingSlipModelStats: Mock;
  getPublishedPredictions: Mock;
  getPublishedPredictionVersions: Mock;
  getPublishedLiveStats: Mock;
  getLiveBetaDashboard?: Mock;
}) {
  apiMocks.getSession.mockResolvedValue({
    id: 1,
    username: "admin",
    is_active: true,
    authenticated: true
  });
  apiMocks.login.mockResolvedValue({
    access_token: "test-token",
    token_type: "bearer",
    expires_at: new Date(Date.now() + 3_600_000).toISOString()
  });
  apiMocks.logout.mockResolvedValue({ ok: true, message: "ok" });
  apiMocks.getGlobalUpdateStatus.mockResolvedValue(idleGlobalUpdate);
  apiMocks.startGlobalUpdate.mockResolvedValue({ run_id: 8, status: "pending" });
  apiMocks.cancelGlobalUpdate.mockResolvedValue({ run_id: 7, status: "cancelled" });
  apiMocks.getGlobalUpdateLatest.mockResolvedValue(idleGlobalUpdate);
  apiMocks.getModelsVersionsResults.mockResolvedValue(modelsCatalog);
  apiMocks.getUpcomingPredictions.mockResolvedValue(makeFixturesPage());
  apiMocks.getNextFixturesPredictions.mockResolvedValue(makeFixturesPage());
  apiMocks.getSingleMatchValueAnalysis.mockResolvedValue(emptyValueAnalysis);
  apiMocks.getImportStatus.mockResolvedValue(importStatus);
  apiMocks.getBettingSlipCalendar.mockResolvedValue(makeCalendar());
  apiMocks.getDailyBettingSlips.mockResolvedValue(makeDailySlips());
  apiMocks.regenerateDailyBettingSlips.mockResolvedValue(makeDailySlips());
  apiMocks.getBettingSlipStats.mockResolvedValue(makeSlipStats());
  apiMocks.getTelegramBotStats.mockResolvedValue(telegramStats);
  apiMocks.getTelegramBotEvents.mockResolvedValue(telegramEvents);
  apiMocks.getPredictionSummary.mockResolvedValue({
    model_version: "v3",
    predictions_total: 0,
    predictions_resolved: 0,
    predictions_correct: 0,
    predictions_lost: 0,
    accuracy_pct: null,
    pending: 0,
    predictions_with_odds: 0,
    avg_predicted_winner_odds: null,
    avg_winning_odds: null,
    theoretical_profit_units: 0,
    theoretical_roi_pct: null,
    breakdown: []
  });
  apiMocks.getDailyPredictionStats.mockResolvedValue({
    model_version: "v3",
    days: []
  });
  apiMocks.getBettingSlipModelStats.mockResolvedValue({
    from_date: "2026-07-01",
    to_date: "2026-07-21",
    stake: 10,
    rows: []
  });
  apiMocks.getPublishedPredictions.mockResolvedValue(publishedPredictions);
  apiMocks.getPublishedPredictionVersions.mockResolvedValue({
    publication_id: publishedPredictions.items[0].publication_id,
    items: publishedPredictions.items
  });
  apiMocks.getPublishedLiveStats.mockResolvedValue(publishedLiveStats);
  apiMocks.getLiveBetaDashboard?.mockResolvedValue(liveBetaDashboard);
}
