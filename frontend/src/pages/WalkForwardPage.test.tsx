import { beforeEach, describe, expect, it, vi } from "vitest";
import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { WalkForwardPage } from "./WalkForwardPage";
import { walkForwardRun, walkForwardRuns } from "../test/fixtures";
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
  startWalkForwardRun: vi.fn()
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

describe("WalkForwardPage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    stubDefaultApi(apiMocks);
  });

  it("shows loading then fold metrics", async () => {
    const pending = deferred<typeof walkForwardRuns>();
    apiMocks.getWalkForwardRuns.mockReturnValue(pending.promise);

    renderWithProviders(<WalkForwardPage />);
    expect(screen.getByText(/Caricamento walk-forward/i)).toBeInTheDocument();

    pending.resolve(walkForwardRuns);
    expect(await screen.findByText(/Validazione walk-forward/i)).toBeInTheDocument();
    expect(screen.getAllByText(/logistic_regression/i).length).toBeGreaterThan(0);
    expect(screen.getAllByText(/market_no_vig/i).length).toBeGreaterThan(0);
    expect(screen.getByText(/Aggregato benchmark ufficiali/i)).toBeInTheDocument();
    expect(screen.getByText(/Pagina versione:/i)).toBeInTheDocument();
    expect(screen.getByText(/Pagina giorno test:/i)).toBeInTheDocument();
    expect(screen.getAllByRole("columnheader", { name: /Brier/i }).length).toBeGreaterThan(0);
  });

  it("shows failed run error prominently", async () => {
    const failedRun = {
      ...walkForwardRun,
      id: 99,
      status: "failed",
      folds: [],
      error_message:
        "Nessun dataset training trovato per versione v1 in /app/backend/data/processed."
    };
    apiMocks.getWalkForwardRuns.mockResolvedValue({
      total: 1,
      limit: 20,
      offset: 0,
      items: [
        {
          ...walkForwardRuns.items[0],
          id: 99,
          status: "failed",
          folds_completed: 0,
          folds_skipped: 0,
          folds_errors: 0
        }
      ]
    });
    apiMocks.getWalkForwardRun.mockResolvedValue(failedRun);

    renderWithProviders(<WalkForwardPage />);
    expect(await screen.findByRole("alert")).toHaveTextContent(/Nessun dataset training/i);
  });

  it("starts a new walk-forward run", async () => {
    const user = userEvent.setup();
    apiMocks.startWalkForwardRun.mockResolvedValue({
      run: walkForwardRun,
      started: true,
      message: "Walk-forward avviato in background."
    });

    renderWithProviders(<WalkForwardPage />);
    expect(await screen.findByText(/Validazione walk-forward/i)).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: /Avvia walk-forward/i }));
    expect(apiMocks.startWalkForwardRun).toHaveBeenCalled();
  });

  it("filters by contender and shows sample mismatch warning", async () => {
    const user = userEvent.setup();
    renderWithProviders(<WalkForwardPage />);
    expect(await screen.findByText(/Validazione walk-forward/i)).toBeInTheDocument();

    await user.selectOptions(screen.getByLabelText(/Contender/i), "elo");
    expect(screen.getByText(/Confronto ufficiale calcolato su campione comune/i)).toBeInTheDocument();
    expect(screen.getByText(/Warning/i)).toBeInTheDocument();
  });
});
