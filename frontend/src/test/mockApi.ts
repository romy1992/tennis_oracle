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
  weeklyBetaReports,
  walkForwardRun,
  walkForwardRuns,
  calibrationRun,
  calibrationRuns,
  probabilityBandAnalysis,
  segmentRoiAnalysis,
  subscriptionDashboardSummary,
  subscriptionDashboardUsers,
  subscriptionDashboardEvents,
  featureFlagsList
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
  getWalkForwardRuns?: Mock;
  getLatestWalkForwardRun?: Mock;
  getWalkForwardRun?: Mock;
  startWalkForwardRun?: Mock;
  getCalibrationRuns?: Mock;
  getLatestCalibrationRun?: Mock;
  getCalibrationRun?: Mock;
  startCalibrationRun?: Mock;
  getProbabilityBandAnalysis?: Mock;
  getSegmentRoiAnalysis?: Mock;
  getSubscriptionsDashboardSummary?: Mock;
  getSubscriptionsDashboardUsers?: Mock;
  getSubscriptionsDashboardEvents?: Mock;
  getSubscriptionsDashboardFeatureFlags?: Mock;
  updateSubscriptionsDashboardFeatureFlag?: Mock;
  suspendDashboardSubscription?: Mock;
  resumeDashboardSubscription?: Mock;
  cancelDashboardSubscription?: Mock;
  exportSubscriptionsDashboardCsv?: Mock;
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
    model_version: "v4",
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
    model_version: "v4",
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
  apiMocks.getWalkForwardRuns?.mockResolvedValue(walkForwardRuns);
  apiMocks.getLatestWalkForwardRun?.mockResolvedValue(walkForwardRun);
  apiMocks.getWalkForwardRun?.mockResolvedValue(walkForwardRun);
  apiMocks.startWalkForwardRun?.mockResolvedValue({
    run: walkForwardRun,
    started: true,
    message: "Walk-forward avviato in background."
  });
  apiMocks.getCalibrationRuns?.mockResolvedValue(calibrationRuns);
  apiMocks.getLatestCalibrationRun?.mockResolvedValue(calibrationRun);
  apiMocks.getCalibrationRun?.mockResolvedValue(calibrationRun);
  apiMocks.startCalibrationRun?.mockResolvedValue({
    run: calibrationRun,
    started: true,
    message: "Calibrazione avviata in background."
  });
  apiMocks.getProbabilityBandAnalysis?.mockResolvedValue(probabilityBandAnalysis);
  apiMocks.getSegmentRoiAnalysis?.mockResolvedValue(segmentRoiAnalysis);
  apiMocks.getSubscriptionsDashboardSummary?.mockResolvedValue(subscriptionDashboardSummary);
  apiMocks.getSubscriptionsDashboardUsers?.mockResolvedValue(subscriptionDashboardUsers);
  apiMocks.getSubscriptionsDashboardEvents?.mockResolvedValue(subscriptionDashboardEvents);
  apiMocks.getSubscriptionsDashboardFeatureFlags?.mockResolvedValue(featureFlagsList);
  apiMocks.updateSubscriptionsDashboardFeatureFlag?.mockImplementation(
    async (featureKey: string, payload: { enabled: boolean }) => {
      const current = featureFlagsList.items.find((item) => item.key === featureKey);
      return {
        key: featureKey,
        enabled: payload.enabled,
        description: current?.description || null,
        updated_at: new Date().toISOString(),
        updated_by: "admin"
      };
    }
  );
  apiMocks.suspendDashboardSubscription?.mockResolvedValue({
    message: "Abbonamento sospeso.",
    subscription: {
      id: 501,
      user_id: 101,
      plan_id: 2,
      status: "suspended",
      started_at: "2026-07-01T00:00:00",
      current_period_start_at: "2026-08-01T00:00:00",
      current_period_end_at: "2026-08-31T00:00:00",
      trial_started_at: null,
      trial_ends_at: null,
      renewed_at: null,
      expires_at: "2026-08-31T00:00:00",
      auto_renew: false,
      cancel_at_period_end: false,
      canceled_at: null,
      cancellation_reason: null,
      suspended_at: "2026-08-02T09:00:00",
      suspension_reason: "manual_review",
      created_at: "2026-07-01T00:00:00",
      updated_at: "2026-08-02T09:00:00"
    }
  });
  apiMocks.resumeDashboardSubscription?.mockResolvedValue({
    message: "Abbonamento riattivato.",
    subscription: {
      id: 501,
      user_id: 101,
      plan_id: 2,
      status: "active",
      started_at: "2026-07-01T00:00:00",
      current_period_start_at: "2026-08-01T00:00:00",
      current_period_end_at: "2026-08-31T00:00:00",
      trial_started_at: null,
      trial_ends_at: null,
      renewed_at: null,
      expires_at: "2026-08-31T00:00:00",
      auto_renew: true,
      cancel_at_period_end: false,
      canceled_at: null,
      cancellation_reason: null,
      suspended_at: null,
      suspension_reason: null,
      created_at: "2026-07-01T00:00:00",
      updated_at: "2026-08-02T09:05:00"
    }
  });
  apiMocks.cancelDashboardSubscription?.mockResolvedValue({
    message: "Abbonamento cancellato.",
    subscription: {
      id: 501,
      user_id: 101,
      plan_id: 2,
      status: "canceled",
      started_at: "2026-07-01T00:00:00",
      current_period_start_at: "2026-08-01T00:00:00",
      current_period_end_at: "2026-08-02T09:10:00",
      trial_started_at: null,
      trial_ends_at: null,
      renewed_at: null,
      expires_at: "2026-08-02T09:10:00",
      auto_renew: false,
      cancel_at_period_end: false,
      canceled_at: "2026-08-02T09:10:00",
      cancellation_reason: "manual_cancel",
      suspended_at: null,
      suspension_reason: null,
      created_at: "2026-07-01T00:00:00",
      updated_at: "2026-08-02T09:10:00"
    }
  });
  apiMocks.exportSubscriptionsDashboardCsv?.mockResolvedValue({
    blob: new Blob(["user_id,username\n101,pro_user\n"], { type: "text/csv" }),
    filename: "subscriptions_dashboard_test.csv"
  });
}
