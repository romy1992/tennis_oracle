import { beforeEach, describe, expect, it, vi } from "vitest";
import { screen } from "@testing-library/react";

import { BettingSlipsPage } from "./BettingSlipsPage";
import { ApiError } from "../services/apiClient";
import { makeCalendar, makeDailySlips } from "../test/fixtures";
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
  getTelegramBotEvents: vi.fn()
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

describe("BettingSlipsPage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    stubDefaultApi(apiMocks);
  });

  it("shows loading then daily slips with version selector", async () => {
    const pending = deferred<ReturnType<typeof makeCalendar>>();
    apiMocks.getBettingSlipCalendar.mockReturnValue(pending.promise);

    renderWithProviders(<BettingSlipsPage />);
    expect(screen.getByText("Caricamento schedine...")).toBeInTheDocument();

    pending.resolve(makeCalendar());

    expect(await screen.findByRole("heading", { name: "Consiglio schedina" })).toBeInTheDocument();
    expect(await screen.findByText("Play facile")).toBeInTheDocument();
    expect(screen.getByLabelText("Versioni modello")).toBeInTheDocument();
    expect(screen.getByLabelText("Modelli")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "v3" })).toHaveClass("active");
  });

  it("shows empty state when the day has no slips", async () => {
    apiMocks.getDailyBettingSlips.mockResolvedValue({
      ...makeDailySlips(),
      slips: []
    });

    renderWithProviders(<BettingSlipsPage />);

    expect(
      await screen.findByText("Nessuna schedina disponibile per questo giorno")
    ).toBeInTheDocument();
  });

  it("shows error state when calendar fails", async () => {
    apiMocks.getGlobalUpdateStatus.mockResolvedValue(null);
    apiMocks.getModelsVersionsResults.mockResolvedValue({
      date: "2026-07-21",
      last_updated_at: null,
      last_run_id: null,
      last_run_origin: null,
      versions: [
        {
          version: "v3",
          models: [
            {
              model: "logistic_regression",
              status: "ok",
              predictions_count: 0,
              slips_count: 0,
              data: {}
            }
          ]
        }
      ]
    });
    apiMocks.getBettingSlipCalendar.mockImplementation(() =>
      Promise.reject(new ApiError("schedine offline", 503))
    );

    renderWithProviders(<BettingSlipsPage />);

    expect(await screen.findByText("Schedine non disponibili")).toBeInTheDocument();
    expect(screen.getByText("schedine offline")).toBeInTheDocument();
  });
});
