import { beforeEach, describe, expect, it, vi } from "vitest";
import { screen } from "@testing-library/react";

import { SegmentRoiPage } from "./SegmentRoiPage";
import { segmentRoiAnalysis } from "../test/fixtures";
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
  startCalibrationRun: vi.fn(),
  getProbabilityBandAnalysis: vi.fn(),
  getSegmentRoiAnalysis: vi.fn()
}));

vi.mock("../services/apiClient", () => ({
  apiClient: apiMocks,
  ApiError: class ApiError extends Error {
    status: number;
    constructor(message: string, status: number) {
      super(message);
      this.status = status;
    }
  }
}));

describe("SegmentRoiPage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    stubDefaultApi(apiMocks);
  });

  it("shows loading then segment ROI table", async () => {
    const pending = deferred<typeof segmentRoiAnalysis>();
    apiMocks.getSegmentRoiAnalysis.mockReturnValue(pending.promise);

    renderWithProviders(<SegmentRoiPage />);
    expect(screen.getByText(/Caricamento ROI per segmento/i)).toBeInTheDocument();

    pending.resolve(segmentRoiAnalysis);
    expect(await screen.findByRole("heading", { name: "ROI per segmento" })).toBeInTheDocument();
    expect(await screen.findByText("Hard")).toBeInTheDocument();
    expect(await screen.findByText(/ROI per superficie/i)).toBeInTheDocument();
  });
});
