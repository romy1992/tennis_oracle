import { beforeEach, describe, expect, it, vi } from "vitest";
import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { TelegramBotPage } from "./TelegramBotPage";
import { ApiError } from "../services/apiClient";
import { telegramEvents, telegramStats } from "../test/fixtures";
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
  getSubscriptionsDashboardFeatureFlags: vi.fn(),
  updateSubscriptionsDashboardFeatureFlag: vi.fn(),
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

describe("TelegramBotPage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    stubDefaultApi(apiMocks);
  });

  it("shows loading then analytics metrics and events", async () => {
    const pendingStats = deferred<typeof telegramStats>();
    apiMocks.getTelegramBotStats.mockReturnValue(pendingStats.promise);
    apiMocks.getTelegramBotEvents.mockResolvedValue(telegramEvents);

    renderWithProviders(<TelegramBotPage />);
    expect(screen.getByText("Caricamento accessi bot...")).toBeInTheDocument();

    pendingStats.resolve(telegramStats);

    expect(await screen.findByRole("heading", { name: "Bot Telegram" })).toBeInTheDocument();
    expect(screen.getByText("Eventi totali")).toBeInTheDocument();
    expect(screen.getByText("12")).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Toggle comandi bot" })).toBeInTheDocument();
    expect(screen.getByText("7 flag")).toBeInTheDocument();
    expect(screen.getByText("Partite (/partite)")).toBeInTheDocument();
    expect(screen.getByText("Abbonamenti (/piano, /abbonati, /gestisci_abbonamento)")).toBeInTheDocument();
    expect(screen.getByText(/Nasconde i comandi abbonamento e SBLOCCA/)).toBeInTheDocument();
    expect(screen.getByLabelText("Comando / azione")).toBeInTheDocument();
    expect(screen.getAllByText("/schedine").length).toBeGreaterThan(0);
    expect(screen.getByText("@tester (Test User)")).toBeInTheDocument();
  });

  it("toggles Telegram command feature flag", async () => {
    const user = userEvent.setup();
    renderWithProviders(<TelegramBotPage />);

    expect(await screen.findByText("Partite (/partite)")).toBeInTheDocument();
    await user.click(screen.getAllByRole("button", { name: "Disattiva" })[0]);

    expect(apiMocks.updateSubscriptionsDashboardFeatureFlag).toHaveBeenCalled();
  });

  it("shows empty events list", async () => {
    apiMocks.getTelegramBotStats.mockResolvedValue({
      ...telegramStats,
      total_events: 0,
      by_action: [],
      by_day: []
    });
    apiMocks.getTelegramBotEvents.mockResolvedValue({ total: 0, limit: 50, offset: 0, items: [] });

    renderWithProviders(<TelegramBotPage />);

    expect(await screen.findByText("Nessun accesso registrato")).toBeInTheDocument();
  });

  it("shows error state when stats fail", async () => {
    apiMocks.getTelegramBotStats.mockImplementation(() =>
      Promise.reject(new ApiError("telegram analytics down", 500))
    );
    apiMocks.getTelegramBotEvents.mockImplementation(() =>
      Promise.reject(new ApiError("telegram analytics down", 500))
    );

    renderWithProviders(<TelegramBotPage />);

    expect(await screen.findByText("Accessi bot non disponibili")).toBeInTheDocument();
    expect(screen.getByText("telegram analytics down")).toBeInTheDocument();
  });
});
