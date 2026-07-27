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
  telegramFeedback,
  telegramStats,
  telegramUsers,
  publishedPredictions,
  publishedLiveStats,
  liveBetaDashboard,
  weeklyBetaReport,
  weeklyBetaReports
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
  getTelegramUsers?: Mock;
  inviteTelegramUser?: Mock;
  activateTelegramUser?: Mock;
  suspendTelegramUser?: Mock;
  blockTelegramUser?: Mock;
  getTelegramFeedback?: Mock;
  updateTelegramFeedbackStatus?: Mock;
  getPredictionSummary: Mock;
  getDailyPredictionStats: Mock;
  getBettingSlipModelStats: Mock;
  getPublishedPredictions: Mock;
  getPublishedPredictionVersions: Mock;
  getPublishedLiveStats: Mock;
  getLiveBetaDashboard?: Mock;
  getWeeklyBetaReports?: Mock;
  getLatestWeeklyBetaReport?: Mock;
  getWeeklyBetaReport?: Mock;
  generateWeeklyBetaReport?: Mock;
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
  apiMocks.getTelegramUsers?.mockResolvedValue(telegramUsers);
  apiMocks.inviteTelegramUser?.mockResolvedValue(telegramUsers.items[0]);
  apiMocks.activateTelegramUser?.mockResolvedValue({
    ...telegramUsers.items[0],
    status: "active"
  });
  apiMocks.suspendTelegramUser?.mockResolvedValue({
    ...telegramUsers.items[0],
    status: "suspended"
  });
  apiMocks.blockTelegramUser?.mockResolvedValue({
    ...telegramUsers.items[0],
    status: "blocked"
  });
  apiMocks.getTelegramFeedback?.mockResolvedValue(telegramFeedback);
  apiMocks.updateTelegramFeedbackStatus?.mockResolvedValue({
    ...telegramFeedback.items[0],
    status: "reviewing"
  });
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
  apiMocks.getWeeklyBetaReports?.mockResolvedValue(weeklyBetaReports);
  apiMocks.getLatestWeeklyBetaReport?.mockResolvedValue(weeklyBetaReport);
  apiMocks.getWeeklyBetaReport?.mockResolvedValue(weeklyBetaReport);
  apiMocks.generateWeeklyBetaReport?.mockResolvedValue({
    report: weeklyBetaReport,
    created: true,
    telegram: { sent: true, telegram: "ok" }
  });
}
