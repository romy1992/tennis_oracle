import { beforeEach, describe, expect, it, vi } from "vitest";
import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { SubscriptionsDashboardPage } from "./SubscriptionsDashboardPage";
import { stubDefaultApi } from "../test/mockApi";
import { deferred, renderWithProviders } from "../test/render";
import { subscriptionDashboardUsers } from "../test/fixtures";

const apiMocks = vi.hoisted(() => ({
  getSession: vi.fn(),
  login: vi.fn(),
  logout: vi.fn(),
  getGlobalUpdateStatus: vi.fn(),
  startGlobalUpdate: vi.fn(),
  cancelGlobalUpdate: vi.fn(),
  getGlobalUpdateLatest: vi.fn(),
  getGlobalUpdateRun: vi.fn(),
  getGlobalUpdateReport: vi.fn(),
  getModelsVersionsResults: vi.fn(),
  getUpcomingPredictions: vi.fn(),
  getNextFixturesPredictions: vi.fn(),
  getSingleMatchValueAnalysis: vi.fn(),
  getImportStatus: vi.fn(),
  importPlayedFixtures: vi.fn(),
  refreshMatches: vi.fn(),
  getBettingSlipCalendar: vi.fn(),
  getDailyBettingSlips: vi.fn(),
  regenerateDailyBettingSlips: vi.fn(),
  refreshBettingSlips: vi.fn(),
  getBettingSlipStats: vi.fn(),
  getBettingSlipModelStats: vi.fn(),
  getPredictionSummary: vi.fn(),
  getDailyPredictionStats: vi.fn(),
  getTelegramBotStats: vi.fn(),
  getTelegramBotEvents: vi.fn(),
  getTelegramUsers: vi.fn(),
  inviteTelegramUser: vi.fn(),
  activateTelegramUser: vi.fn(),
  suspendTelegramUser: vi.fn(),
  blockTelegramUser: vi.fn(),
  getTelegramFeedback: vi.fn(),
  updateTelegramFeedbackStatus: vi.fn(),
  getPublishedPredictions: vi.fn(),
  getPublishedPredictionVersions: vi.fn(),
  getPublishedLiveStats: vi.fn(),
  getLiveBetaDashboard: vi.fn(),
  getWeeklyBetaReports: vi.fn(),
  getLatestWeeklyBetaReport: vi.fn(),
  getWeeklyBetaReport: vi.fn(),
  generateWeeklyBetaReport: vi.fn(),
  getWalkForwardRuns: vi.fn(),
  getLatestWalkForwardRun: vi.fn(),
  getWalkForwardRun: vi.fn(),
  startWalkForwardRun: vi.fn(),
  getCalibrationRuns: vi.fn(),
  getLatestCalibrationRun: vi.fn(),
  getCalibrationRun: vi.fn(),
  startCalibrationRun: vi.fn(),
  getProbabilityBandAnalysis: vi.fn(),
  getSegmentRoiAnalysis: vi.fn(),
  getSubscriptionsDashboardSummary: vi.fn(),
  getSubscriptionsDashboardUsers: vi.fn(),
  getSubscriptionsDashboardEvents: vi.fn(),
  suspendDashboardSubscription: vi.fn(),
  resumeDashboardSubscription: vi.fn(),
  cancelDashboardSubscription: vi.fn(),
  exportSubscriptionsDashboardCsv: vi.fn()
}));

vi.mock("../services/apiClient", async () => {
  const actual = await vi.importActual<typeof import("../services/apiClient")>(
    "../services/apiClient"
  );
  return {
    ...actual,
    apiClient: {
      ...actual.apiClient,
      ...apiMocks
    }
  };
});

describe("SubscriptionsDashboardPage", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    vi.clearAllMocks();
    stubDefaultApi(apiMocks);
    vi.spyOn(window, "prompt").mockReturnValue("manual_review");
    vi.spyOn(window, "confirm").mockReturnValue(true);
    Object.defineProperty(window.URL, "createObjectURL", {
      configurable: true,
      value: vi.fn(() => "blob:dashboard")
    });
    Object.defineProperty(window.URL, "revokeObjectURL", {
      configurable: true,
      value: vi.fn()
    });
    vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => {});
  });

  it("shows metrics and users table", async () => {
    const pending = deferred<typeof subscriptionDashboardUsers>();
    apiMocks.getSubscriptionsDashboardUsers.mockReturnValue(pending.promise);

    renderWithProviders(<SubscriptionsDashboardPage />);
    expect(screen.getByText(/Caricamento/i)).toBeInTheDocument();

    pending.resolve(subscriptionDashboardUsers);

    expect(await screen.findByRole("heading", { name: "Dashboard abbonamenti" })).toBeInTheDocument();
    expect(screen.getByText("Utenti Pro")).toBeInTheDocument();
    expect(screen.getByText("@pro_user")).toBeInTheDocument();
    expect(screen.getAllByRole("button", { name: "Sospendi" }).length).toBeGreaterThan(0);
  });

  it("runs manual suspend action", async () => {
    const user = userEvent.setup();
    renderWithProviders(<SubscriptionsDashboardPage />);

    expect(await screen.findByText("@pro_user")).toBeInTheDocument();
    await user.click(screen.getAllByRole("button", { name: "Sospendi" })[0]);

    expect(apiMocks.suspendDashboardSubscription).toHaveBeenCalledWith(501, "manual_review");
  });

  it("exports CSV", async () => {
    const user = userEvent.setup();
    renderWithProviders(<SubscriptionsDashboardPage />);

    expect(await screen.findByRole("button", { name: "Esporta CSV" })).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Esporta CSV" }));

    expect(apiMocks.exportSubscriptionsDashboardCsv).toHaveBeenCalled();
  });
});



