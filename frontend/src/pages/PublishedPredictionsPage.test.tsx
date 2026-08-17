import { beforeEach, describe, expect, it, vi } from "vitest";
import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { PublishedPredictionsPage } from "./PublishedPredictionsPage";
import { stubDefaultApi } from "../test/mockApi";
import { publishedPredictions } from "../test/fixtures";
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

describe("PublishedPredictionsPage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    stubDefaultApi(apiMocks);
  });

  it("renders published prediction history", async () => {
    renderWithProviders(<PublishedPredictionsPage />);
    expect(await screen.findByText("Storico pubblicazioni")).toBeInTheDocument();
    expect(await screen.findByText("Player A vs Player B")).toBeInTheDocument();
    expect(apiMocks.getPublishedPredictions).toHaveBeenCalledWith(
      expect.objectContaining({
        market: "match_winner",
        include_archived: false,
        latest_only: true
      })
    );
    expect(screen.getByRole("tab", { name: "Vincitore partita" })).toBeInTheDocument();
    expect(screen.getAllByText("Vincitore partita").length).toBeGreaterThan(0);
  });

  it("loads version chain on button click", async () => {
    const user = userEvent.setup();
    renderWithProviders(<PublishedPredictionsPage />);
    await screen.findByText("Player A vs Player B");
    await user.click(screen.getByRole("button", { name: "Versioni" }));
    expect(apiMocks.getPublishedPredictionVersions).toHaveBeenCalledWith(
      publishedPredictions.items[0].publication_id
    );
    expect(await screen.findByText("Catena versioni")).toBeInTheDocument();
  });
});
