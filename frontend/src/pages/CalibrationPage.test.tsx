import { beforeEach, describe, expect, it, vi } from "vitest";
import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { CalibrationPage } from "./CalibrationPage";
import { calibrationRun, calibrationRuns } from "../test/fixtures";
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
  generateWeeklyBetaReport: vi.fn(),
  getWalkForwardRuns: vi.fn(),
  getLatestWalkForwardRun: vi.fn(),
  getWalkForwardRun: vi.fn(),
  startWalkForwardRun: vi.fn(),
  getCalibrationRuns: vi.fn(),
  getLatestCalibrationRun: vi.fn(),
  getCalibrationRun: vi.fn(),
  startCalibrationRun: vi.fn()
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

describe("CalibrationPage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    stubDefaultApi(apiMocks);
  });

  it("shows loading then calibration metrics", async () => {
    const pending = deferred<typeof calibrationRuns>();
    apiMocks.getCalibrationRuns.mockReturnValue(pending.promise);

    renderWithProviders(<CalibrationPage />);
    expect(screen.getByText(/Caricamento calibrazione/i)).toBeInTheDocument();

    pending.resolve(calibrationRuns);
    expect(await screen.findByText(/Calibrazione probabilità/i)).toBeInTheDocument();
    expect(screen.getByText(/ECE grezzo/i)).toBeInTheDocument();
  });

  it("starts a new calibration run", async () => {
    const user = userEvent.setup();
    apiMocks.startCalibrationRun.mockResolvedValue({
      run: calibrationRun,
      started: true,
      message: "Calibrazione avviata in background."
    });

    renderWithProviders(<CalibrationPage />);
    expect(await screen.findByText(/Calibrazione probabilità/i)).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: /Avvia calibrazione/i }));
    expect(apiMocks.startCalibrationRun).toHaveBeenCalled();
  });
});
