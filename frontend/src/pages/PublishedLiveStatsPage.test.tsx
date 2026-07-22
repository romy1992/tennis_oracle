import { beforeEach, describe, expect, it, vi } from "vitest";
import { screen } from "@testing-library/react";

import { PublishedLiveStatsPage } from "./PublishedLiveStatsPage";
import { stubDefaultApi } from "../test/mockApi";
import { publishedLiveStats } from "../test/fixtures";
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
  getPublishedLiveStats: vi.fn()
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

describe("PublishedLiveStatsPage", () => {
  beforeEach(() => {
    stubDefaultApi(apiMocks);
  });

  it("shows live tipbook KPIs from the published ledger", async () => {
    renderWithProviders(<PublishedLiveStatsPage />);
    expect(await screen.findByRole("heading", { name: /statistiche live/i })).toBeInTheDocument();
    expect(apiMocks.getPublishedLiveStats).toHaveBeenCalled();
    expect(screen.getByText(String(publishedLiveStats.predictions_total))).toBeInTheDocument();
    expect(screen.getAllByText("Hit rate").length).toBeGreaterThan(0);
    expect(screen.getByText("Max drawdown")).toBeInTheDocument();
    expect(screen.getByText("Per modello")).toBeInTheDocument();
  });
});
