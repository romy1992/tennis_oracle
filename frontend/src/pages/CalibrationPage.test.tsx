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

  it("shows the production calibration for each active market", async () => {
    const user = userEvent.setup();
    const baseResult = calibrationRun.results[0];
    apiMocks.getCalibrationRun.mockResolvedValue({
      ...calibrationRun,
      versions_requested: "first_set_winner_v2,over_under_games_v1,v4",
      results: [
        {
          ...baseResult,
          id: 32,
          model_version: "v4",
          model_name: "voting_ensemble"
        },
        {
          ...baseResult,
          id: 33,
          model_version: "first_set_winner_v2",
          model_name: "logistic_regression",
          oos_samples_total: 123
        },
        {
          ...baseResult,
          id: 34,
          model_version: "over_under_games_v1",
          model_name: "random_forest",
          oos_samples_total: 234
        }
      ]
    });

    renderWithProviders(<CalibrationPage />);
    expect(await screen.findByText(/Calibrazione probabilità/i)).toBeInTheDocument();

    await user.click(screen.getByRole("tab", { name: "Vincitore 1° set" }));
    expect(screen.getByLabelText("Modello")).toHaveValue("logistic_regression");
    expect(screen.getByText("123")).toBeInTheDocument();
    expect(screen.queryByText(/Calibrazione non disponibile/i)).not.toBeInTheDocument();

    await user.click(screen.getByRole("tab", { name: "Over/Under games" }));
    expect(screen.getByLabelText("Modello")).toHaveValue("random_forest");
    expect(screen.getByText("234")).toBeInTheDocument();
  });
});
