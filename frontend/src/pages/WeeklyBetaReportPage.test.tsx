import { beforeEach, describe, expect, it, vi } from "vitest";
import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { WeeklyBetaReportPage } from "./WeeklyBetaReportPage";
import { ApiError } from "../services/apiClient";
import { weeklyBetaReport, weeklyBetaReports } from "../test/fixtures";
import { stubDefaultApi } from "../test/mockApi";
import { deferred, renderWithProviders } from "../test/render";

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
  generateWeeklyBetaReport: vi.fn()
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

describe("WeeklyBetaReportPage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    stubDefaultApi(apiMocks);
  });

  it("shows loading then report metrics", async () => {
    const pending = deferred<typeof weeklyBetaReports>();
    apiMocks.getWeeklyBetaReports.mockReturnValue(pending.promise);

    renderWithProviders(<WeeklyBetaReportPage />);
    expect(screen.getByText(/Caricamento report settimanale/i)).toBeInTheDocument();

    pending.resolve(weeklyBetaReports);

    expect(
      await screen.findByRole("heading", { name: "Report settimanale beta" })
    ).toBeInTheDocument();
    expect(await screen.findByText("2026-W29")).toBeInTheDocument();
    expect(screen.getAllByText("Utenti attivi").length).toBeGreaterThan(0);
    expect(screen.getByText("Retention W1")).toBeInTheDocument();
    expect(screen.getByText("Max drawdown")).toBeInTheDocument();
  });

  it("generates a report on button click", async () => {
    const user = userEvent.setup();
    renderWithProviders(<WeeklyBetaReportPage />);
    expect(await screen.findByRole("heading", { name: "Report settimanale beta" })).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Genera ultima settimana" }));
    expect(apiMocks.generateWeeklyBetaReport).toHaveBeenCalledWith({
      send_telegram: true,
      force: false
    });
  });

  it("shows empty state when no reports", async () => {
    apiMocks.getWeeklyBetaReports.mockResolvedValue({
      total: 0,
      limit: 20,
      offset: 0,
      items: []
    });
    renderWithProviders(<WeeklyBetaReportPage />);
    expect(await screen.findByText("Nessun report ancora")).toBeInTheDocument();
  });

  it("shows error state", async () => {
    apiMocks.getWeeklyBetaReports.mockRejectedValue(new ApiError("boom", 500));
    renderWithProviders(<WeeklyBetaReportPage />);
    expect(await screen.findByText("boom")).toBeInTheDocument();
  });
});
