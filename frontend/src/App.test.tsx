import { beforeEach, describe, expect, it, vi } from "vitest";
import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { ApiError } from "./services/apiClient";
import { stubDefaultApi } from "./test/mockApi";
import { renderApp } from "./test/render";

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

vi.mock("./services/apiClient", async () => {
  const actual = await vi.importActual<typeof import("./services/apiClient")>(
    "./services/apiClient"
  );
  return {
    ...actual,
    apiClient: {
      ...actual.apiClient,
      ...apiMocks
    }
  };
});

describe("App navigation and auth", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    stubDefaultApi(apiMocks);
  });

  it("redirects unauthenticated users from admin routes to login", async () => {
    apiMocks.getSession.mockRejectedValue(new ApiError("Unauthorized", 401));
    apiMocks.getGlobalUpdateStatus.mockResolvedValue(null);

    renderApp({ authenticated: false, initialEntries: ["/predictions"] });

    expect(await screen.findByRole("heading", { name: "tennis_oracle" })).toBeInTheDocument();
    expect(screen.getByText(/Accedi con l'account amministratore/i)).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Partite" })).not.toBeInTheDocument();
  });

  it("boots authenticated shell on predictions and navigates to betting slips", async () => {
    const user = userEvent.setup();
    renderApp({ initialEntries: ["/predictions"] });

    expect(await screen.findByRole("heading", { name: "Partite" })).toBeInTheDocument();
    expect(screen.getByText("admin")).toBeInTheDocument();

    await user.click(screen.getByRole("link", { name: "Consiglio schedina" }));
    expect(await screen.findByRole("heading", { name: "Consiglio schedina" })).toBeInTheDocument();
  });

  it("opens Telegram analytics from the sidebar", async () => {
    renderApp({ initialEntries: ["/telegram-bot"] });
    expect(await screen.findByRole("heading", { name: "Bot Telegram" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Bot Telegram" })).toHaveClass("active");
  });

  it("redirects index to predictions when authenticated", async () => {
    renderApp({ initialEntries: ["/"] });
    expect(await screen.findByRole("heading", { name: "Partite" })).toBeInTheDocument();
  });
});
