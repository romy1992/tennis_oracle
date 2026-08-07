import { beforeEach, describe, expect, it, vi } from "vitest";
import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { GlobalUpdateControls } from "./GlobalUpdateControls";
import { ApiError } from "../services/apiClient";
import { idleGlobalUpdate, runningGlobalUpdate } from "../test/fixtures";
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

describe("GlobalUpdateControls", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    stubDefaultApi(apiMocks);
  });

  it("shows last completed run and triggers a new global update", async () => {
    apiMocks.getGlobalUpdateStatus.mockResolvedValue(idleGlobalUpdate);
    apiMocks.startGlobalUpdate.mockResolvedValue({ run_id: 8, status: "pending" });
    const user = userEvent.setup();

    renderWithProviders(<GlobalUpdateControls />);

    expect(await screen.findByRole("button", { name: "Aggiorna tutto" })).toBeInTheDocument();
    expect(screen.getByText(/Ultimo:/)).toBeInTheDocument();

    apiMocks.getGlobalUpdateStatus.mockResolvedValue(runningGlobalUpdate);
    await user.click(screen.getByRole("button", { name: "Aggiorna tutto" }));

    await waitFor(() => {
      expect(apiMocks.startGlobalUpdate).toHaveBeenCalledWith({ force: true });
    });
    expect(await screen.findByRole("button", { name: "Aggiornamento globale..." })).toBeDisabled();
    expect(screen.getByText("predictions")).toBeInTheDocument();
    expect(screen.getByText("42%")).toBeInTheDocument();
  });

  it("lets the user restrict the update to a subset of versions", async () => {
    apiMocks.getGlobalUpdateStatus.mockResolvedValue(idleGlobalUpdate);
    apiMocks.startGlobalUpdate.mockResolvedValue({ run_id: 9, status: "pending" });
    const user = userEvent.setup();

    renderWithProviders(<GlobalUpdateControls />);
    await screen.findByRole("button", { name: "Aggiorna tutto" });

    await user.click(screen.getByRole("checkbox", { name: "v1" }));
    await user.click(screen.getByRole("checkbox", { name: "v2" }));

    const partialButton = await screen.findByRole("button", { name: /Aggiorna selezionate/ });
    await user.click(partialButton);

    await waitFor(() => {
      expect(apiMocks.startGlobalUpdate).toHaveBeenCalledWith({
        force: true,
        versions: ["v3", "v4"]
      });
    });
  });

  it("surfaces API errors from the trigger action", async () => {
    apiMocks.getGlobalUpdateStatus.mockResolvedValue(idleGlobalUpdate);
    apiMocks.startGlobalUpdate.mockRejectedValue(new ApiError("Run già attiva", 409));
    const user = userEvent.setup();

    renderWithProviders(<GlobalUpdateControls />);
    await screen.findByRole("button", { name: "Aggiorna tutto" });
    await user.click(screen.getByRole("button", { name: "Aggiorna tutto" }));

    expect(await screen.findByText("Run già attiva")).toBeInTheDocument();
  });

  it("can cancel a running update", async () => {
    apiMocks.getGlobalUpdateStatus.mockResolvedValue(runningGlobalUpdate);
    apiMocks.cancelGlobalUpdate.mockResolvedValue({ run_id: 7, status: "cancelled" });
    const user = userEvent.setup();

    renderWithProviders(<GlobalUpdateControls />);
    expect(await screen.findByRole("button", { name: "Annulla" })).toBeInTheDocument();

    apiMocks.getGlobalUpdateStatus.mockResolvedValue({ ...idleGlobalUpdate, status: "cancelled" });
    await user.click(screen.getByRole("button", { name: "Annulla" }));

    await waitFor(() => {
      expect(apiMocks.cancelGlobalUpdate).toHaveBeenCalledWith(7);
    });
  });
});
