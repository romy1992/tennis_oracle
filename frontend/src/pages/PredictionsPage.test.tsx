import { beforeEach, describe, expect, it, vi } from "vitest";
import { screen, waitFor } from "@testing-library/react";

import { PredictionsPage } from "./PredictionsPage";
import { ApiError } from "../services/apiClient";
import { makeFixture, makeFixturesPage, modelsCatalog } from "../test/fixtures";
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

describe("PredictionsPage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    stubDefaultApi(apiMocks);
  });

  it("shows loading then fixture rows with model version controls", async () => {
    const pending = deferred<ReturnType<typeof makeFixturesPage>>();
    apiMocks.getUpcomingPredictions.mockReturnValue(pending.promise);

    renderWithProviders(<PredictionsPage />);
    expect(screen.getByText("Caricamento partite...")).toBeInTheDocument();

    pending.resolve(makeFixturesPage([makeFixture()]));

    expect(await screen.findByRole("heading", { name: "Partite" })).toBeInTheDocument();
    expect(screen.getByText(/Player A vs/)).toBeInTheDocument();
    expect(screen.getByLabelText("Versioni modello")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "v3" })).toHaveClass("active");
    expect(screen.getByRole("button", { name: "v2" })).toBeInTheDocument();
  });

  it("shows empty state when there are no fixtures", async () => {
    apiMocks.getUpcomingPredictions.mockResolvedValue(makeFixturesPage([]));

    renderWithProviders(<PredictionsPage />);

    expect(await screen.findByText("Nessuna partita")).toBeInTheDocument();
  });

  it("shows error state when predictions fail to load", async () => {
    apiMocks.getGlobalUpdateStatus.mockResolvedValue(null);
    apiMocks.getModelsVersionsResults.mockResolvedValue({
      ...modelsCatalog,
      versions: [modelsCatalog.versions[0]]
    });
    apiMocks.getUpcomingPredictions.mockImplementation(() =>
      Promise.reject(new ApiError("backend down", 500))
    );

    renderWithProviders(<PredictionsPage />);

    expect(await screen.findByText("Partite non disponibili")).toBeInTheDocument();
    expect(screen.getByText("backend down")).toBeInTheDocument();
  });

  it("loads predictions for each available model of the active version", async () => {
    apiMocks.getUpcomingPredictions.mockResolvedValue(makeFixturesPage([]));

    renderWithProviders(<PredictionsPage />);
    await screen.findByText("Nessuna partita");

    await waitFor(() => {
      expect(apiMocks.getUpcomingPredictions).toHaveBeenCalled();
    });
    const versions = apiMocks.getUpcomingPredictions.mock.calls.map(
      (call) => call[0]?.model_version
    );
    const names = apiMocks.getUpcomingPredictions.mock.calls.map((call) => call[0]?.model_name);
    expect(versions.every((v) => v === "v3")).toBe(true);
    expect(names).toEqual(expect.arrayContaining(["logistic_regression", "random_forest"]));
  });
});
