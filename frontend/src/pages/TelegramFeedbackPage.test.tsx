import { beforeEach, describe, expect, it, vi } from "vitest";
import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { TelegramFeedbackPage } from "./TelegramFeedbackPage";
import { ApiError } from "../services/apiClient";
import { telegramFeedback } from "../test/fixtures";
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

describe("TelegramFeedbackPage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    stubDefaultApi(apiMocks);
  });

  it("shows loading then feedback list", async () => {
    const pending = deferred<typeof telegramFeedback>();
    apiMocks.getTelegramFeedback.mockReturnValue(pending.promise);

    renderWithProviders(<TelegramFeedbackPage />);
    expect(screen.getByText(/Caricamento/i)).toBeInTheDocument();

    pending.resolve(telegramFeedback);

    expect(await screen.findByRole("heading", { name: "Feedback Telegram" })).toBeInTheDocument();
    expect(screen.getByText("@tester (Test User)")).toBeInTheDocument();
    expect(screen.getByText("La schedina di oggi non si apre.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Reviewing" })).toBeInTheDocument();
  });

  it("updates feedback status from the table", async () => {
    const user = userEvent.setup();
    renderWithProviders(<TelegramFeedbackPage />);
    expect(await screen.findByText("@tester (Test User)")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Reviewing" }));
    expect(apiMocks.updateTelegramFeedbackStatus).toHaveBeenCalledWith(7, {
      status: "reviewing"
    });
  });

  it("shows error state when list fails", async () => {
    apiMocks.getTelegramFeedback.mockImplementation(() =>
      Promise.reject(new ApiError("telegram feedback down", 500))
    );

    renderWithProviders(<TelegramFeedbackPage />);

    expect(await screen.findByText("Feedback Telegram non disponibili")).toBeInTheDocument();
    expect(screen.getByText("telegram feedback down")).toBeInTheDocument();
  });
});
