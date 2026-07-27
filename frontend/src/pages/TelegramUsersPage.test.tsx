import { beforeEach, describe, expect, it, vi } from "vitest";
import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { TelegramUsersPage } from "./TelegramUsersPage";
import { ApiError } from "../services/apiClient";
import { telegramUsers } from "../test/fixtures";
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

describe("TelegramUsersPage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    stubDefaultApi(apiMocks);
  });

  it("shows loading then users list", async () => {
    const pending = deferred<typeof telegramUsers>();
    apiMocks.getTelegramUsers.mockReturnValue(pending.promise);

    renderWithProviders(<TelegramUsersPage />);
    expect(screen.getByText(/Caricamento/i)).toBeInTheDocument();

    pending.resolve(telegramUsers);

    expect(await screen.findByRole("heading", { name: "Utenti beta Telegram" })).toBeInTheDocument();
    expect(screen.getByText("@tester (Test User)")).toBeInTheDocument();
    expect(screen.getByText("beta_wave1")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Attiva" })).toBeInTheDocument();
  });

  it("activates a user from the table", async () => {
    const user = userEvent.setup();
    renderWithProviders(<TelegramUsersPage />);
    expect(await screen.findByText("@tester (Test User)")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Attiva" }));
    expect(apiMocks.activateTelegramUser).toHaveBeenCalledWith(42);
  });

  it("shows error state when list fails", async () => {
    apiMocks.getTelegramUsers.mockImplementation(() =>
      Promise.reject(new ApiError("telegram users down", 500))
    );

    renderWithProviders(<TelegramUsersPage />);

    expect(await screen.findByText("Utenti Telegram non disponibili")).toBeInTheDocument();
    expect(screen.getByText("telegram users down")).toBeInTheDocument();
  });
});
