import { beforeEach, describe, expect, it, vi } from "vitest";
import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { LiveBetaDashboardPage } from "./LiveBetaDashboardPage";
import { stubDefaultApi } from "../test/mockApi";
import { renderWithProviders } from "../test/render";

const apiMocks = vi.hoisted(() => ({
  getSession: vi.fn(),
  login: vi.fn(),
  logout: vi.fn(),
  getGlobalUpdateStatus: vi.fn(),
  startGlobalUpdate: vi.fn(),
  cancelGlobalUpdate: vi.fn(),
  getGlobalUpdateLatest: vi.fn(),
  getModelsVersionsResults: vi.fn(),
  getUpcomingPredictions: vi.fn(),
  getNextFixturesPredictions: vi.fn(),
  getSingleMatchValueAnalysis: vi.fn(),
  getImportStatus: vi.fn(),
  getBettingSlipCalendar: vi.fn(),
  getDailyBettingSlips: vi.fn(),
  regenerateDailyBettingSlips: vi.fn(),
  getBettingSlipStats: vi.fn(),
  getBettingSlipModelStats: vi.fn(),
  getPredictionSummary: vi.fn(),
  getDailyPredictionStats: vi.fn(),
  getTelegramBotStats: vi.fn(),
  getTelegramBotEvents: vi.fn(),
  getPublishedPredictions: vi.fn(),
  getPublishedPredictionVersions: vi.fn(),
  getPublishedLiveStats: vi.fn(),
  getLiveBetaDashboard: vi.fn()
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

describe("LiveBetaDashboardPage", () => {
  beforeEach(() => {
    stubDefaultApi(apiMocks);
  });

  it("renders live beta panels and keeps backtest separated", async () => {
    renderWithProviders(<LiveBetaDashboardPage />);

    expect(
      await screen.findByRole("heading", { name: /dashboard beta live/i })
    ).toBeInTheDocument();
    expect(apiMocks.getLiveBetaDashboard).toHaveBeenCalled();
    expect(screen.getByText("Pipeline LIVE")).toBeInTheDocument();
    expect(screen.getByText("Pronostici pubblicati oggi")).toBeInTheDocument();
    expect(screen.getByText("Completezza dati")).toBeInTheDocument();
    expect(screen.getByText("Errori recenti")).toBeInTheDocument();
    expect(screen.getByText("Max drawdown")).toBeInTheDocument();
    expect(screen.getByText("Pronostici totali")).toBeInTheDocument();
    expect(screen.getByText("BACKTEST")).toBeInTheDocument();
    expect(screen.getByText(/Area separata/i)).toBeInTheDocument();
    expect(screen.getByText(/non include metriche di training/i)).toBeInTheDocument();
  });

  it("passes tournament and odds-band filters to the API", async () => {
    const user = userEvent.setup();
    renderWithProviders(<LiveBetaDashboardPage />);
    await screen.findByRole("heading", { name: /dashboard beta live/i });

    const tournament = screen.getByPlaceholderText(/roland garros/i);
    await user.clear(tournament);
    await user.type(tournament, "Beta Open");
    await user.tab();
    await user.selectOptions(screen.getByLabelText(/fascia quota/i), "2_00_3_00");

    await waitFor(() => {
      expect(apiMocks.getLiveBetaDashboard).toHaveBeenCalledWith(
        expect.objectContaining({
          tournament_name: "Beta Open",
          odds_band: "2_00_3_00"
        })
      );
    });
  });
});
