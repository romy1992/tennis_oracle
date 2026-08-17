import { beforeEach, describe, expect, it, vi } from "vitest";
import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { LiveBetaDashboardPage } from "./LiveBetaDashboardPage";
import { stubDefaultApi } from "../test/mockApi";
import { liveBetaDashboard } from "../test/fixtures";
import { renderWithProviders } from "../test/render";
import type { LiveBetaDashboardResponse } from "../types/api";

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

function firstSetDashboard(): LiveBetaDashboardResponse {
  const firstSetTip = {
    ...liveBetaDashboard.published_today[0],
    market: "first_set_winner",
    selection: "Player A",
    odds: null,
    void_odds: null,
    edge: null,
    publication_odds: null,
    closing_odds: null,
    clv_pct: null,
    value_decision: null,
    official_play: false
  };
  return {
    ...liveBetaDashboard,
    market: "first_set_winner",
    include_archived: false,
    live_stats: {
      ...liveBetaDashboard.live_stats,
      market: "first_set_winner",
      predictions_total: 1,
      open: 1,
      closed: 0,
      void: 0,
      won: 0,
      lost: 0,
      hit_rate_pct: null,
      stake_total: 0,
      stake_settled: 0,
      profit: 0,
      roi_pct: null,
      yield_pct: null,
      max_drawdown: 0,
      clv_avg_pct: null
    },
    official_live_stats: {
      ...liveBetaDashboard.live_stats,
      market: "first_set_winner",
      official_only: true,
      predictions_total: 0,
      open: 0,
      closed: 0,
      void: 0,
      won: 0,
      lost: 0,
      hit_rate_pct: null,
      stake_total: 0,
      stake_settled: 0,
      profit: 0,
      roi_pct: null,
      yield_pct: null,
      max_drawdown: 0,
      clv_avg_pct: null
    },
    published_today: [firstSetTip],
    open_predictions: [firstSetTip],
    closed_predictions: [],
    data_completeness: {
      ...liveBetaDashboard.data_completeness,
      tips_total: 1,
      tips_with_odds: 0,
      tips_with_odds_pct: 0,
      odds_snapshot_coverage_pct: 0
    }
  };
}

describe("LiveBetaDashboardPage", () => {
  beforeEach(() => {
    stubDefaultApi(apiMocks);
  });

  it("renders a market-specific live dashboard and separates all tips from official PLAY", async () => {
    renderWithProviders(<LiveBetaDashboardPage />);

    expect(
      await screen.findByRole("heading", { name: /^dashboard live$/i })
    ).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: "Vincitore partita" })).toHaveAttribute(
      "aria-selected",
      "true"
    );
    expect(screen.getByRole("tab", { name: "Vincitore 1° set" })).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: "Over/Under games" })).toBeInTheDocument();
    expect(screen.queryByRole("tab", { name: "Tutte" })).not.toBeInTheDocument();

    expect(screen.getByRole("heading", { name: "Tutti i pronostici" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "PLAY ufficiali" })).toBeInTheDocument();
    expect(screen.getAllByText("Profitto (unità)").length).toBeGreaterThan(0);
    expect(screen.getByText("Max drawdown (unità)")).toBeInTheDocument();
    expect(screen.queryByText("Yield")).not.toBeInTheDocument();
    expect(screen.queryByText("BACKTEST")).not.toBeInTheDocument();
    expect(screen.queryByLabelText("Versione modello")).not.toBeInTheDocument();
    expect(screen.queryByLabelText(/^Modello$/)).not.toBeInTheDocument();
    expect(screen.getByLabelText("Data pubblicazione da")).toBeInTheDocument();
    expect(screen.getByLabelText("Data pubblicazione a")).toBeInTheDocument();
    expect(screen.getByLabelText(/Includi storico/)).toBeInTheDocument();
    expect(screen.getAllByText(/1 mostrati · limite 25/)).toHaveLength(3);
    expect(screen.getAllByText("PLAY").length).toBeGreaterThan(1);
    expect(screen.queryByText(/v4 \/ voting_ensemble/)).not.toBeInTheDocument();

    expect(apiMocks.getLiveBetaDashboard).toHaveBeenCalledWith(
      expect.objectContaining({
        market: "match_winner",
        include_archived: false,
        official_only: false,
        latest_only: true,
        tip_limit: 25
      })
    );
  });

  it("shows history only for match winner and resets it on another market", async () => {
    const user = userEvent.setup();
    renderWithProviders(<LiveBetaDashboardPage />);
    await screen.findByRole("heading", { name: /^dashboard live$/i });

    await user.click(screen.getByLabelText(/Includi storico/));
    await waitFor(() => {
      expect(apiMocks.getLiveBetaDashboard).toHaveBeenCalledWith(
        expect.objectContaining({ market: "match_winner", include_archived: true })
      );
    });

    await user.click(screen.getByRole("tab", { name: "Over/Under games" }));
    await screen.findByRole("heading", { name: /^dashboard live$/i });
    expect(screen.queryByLabelText(/Includi storico/)).not.toBeInTheDocument();
    expect(screen.getByLabelText("Fascia quota")).toBeInTheDocument();
    await waitFor(() => {
      expect(apiMocks.getLiveBetaDashboard).toHaveBeenCalledWith(
        expect.objectContaining({ market: "over_under_games", include_archived: false })
      );
    });
  });

  it("renders first-set market like other quoted markets and hides archived filter", async () => {
    apiMocks.getLiveBetaDashboard.mockImplementation(
      async (params: { market?: string }) =>
        params.market === "first_set_winner" ? firstSetDashboard() : liveBetaDashboard
    );
    const user = userEvent.setup();
    renderWithProviders(<LiveBetaDashboardPage />);
    await screen.findByRole("heading", { name: /^dashboard live$/i });

    await user.click(screen.getByRole("tab", { name: "Vincitore 1° set" }));
    const officialSection = (
      await screen.findByRole("heading", { name: "PLAY ufficiali" })
    ).closest("article");
    expect(officialSection).not.toBeNull();
    expect(screen.queryByLabelText(/Includi storico/)).not.toBeInTheDocument();
    expect(screen.getByLabelText("Fascia quota")).toBeInTheDocument();
    expect(screen.getAllByText("Non PLAY").length).toBeGreaterThan(0);
    expect(screen.getAllByText("Vincitore 1° set").length).toBeGreaterThan(1);

    expect(apiMocks.getLiveBetaDashboard).toHaveBeenCalledWith(
      expect.objectContaining({
        market: "first_set_winner",
        include_archived: false,
        official_only: false
      })
    );
  });

  it("shows a readable global publication diagnostic", async () => {
    apiMocks.getLiveBetaDashboard.mockResolvedValueOnce({
      ...liveBetaDashboard,
      publication_health: {
        ...liveBetaDashboard.publication_health,
        empty_reason: "publication_disabled",
        message:
          "Nessuna pubblicazione automatica: la pipeline non scrive nel registro live.",
        live_publication_enabled: false
      }
    });

    renderWithProviders(<LiveBetaDashboardPage />);
    expect(await screen.findByText("Pubblicazione disabilitata")).toBeInTheDocument();
    expect(screen.getByText("Disabilitata")).toBeInTheDocument();
    expect(screen.queryByText("publication_disabled")).not.toBeInTheDocument();
  });

  it("passes publication, tournament and odds filters to the market-aware API", async () => {
    const user = userEvent.setup();
    renderWithProviders(<LiveBetaDashboardPage />);
    await screen.findByRole("heading", { name: /^dashboard live$/i });

    const tournament = screen.getByPlaceholderText(/roland garros/i);
    await user.clear(tournament);
    await user.type(tournament, "Beta Open");
    await user.tab();
    await user.selectOptions(screen.getByLabelText("Fascia quota"), "2_00_3_00");

    await waitFor(() => {
      expect(apiMocks.getLiveBetaDashboard).toHaveBeenCalledWith(
        expect.objectContaining({
          market: "match_winner",
          tournament_name: "Beta Open",
          odds_band: "2_00_3_00"
        })
      );
    });
  });

  it("keeps legacy responses readable without inventing official financial metrics", async () => {
    const legacy = { ...liveBetaDashboard } as LiveBetaDashboardResponse;
    delete legacy.market;
    delete legacy.include_archived;
    delete legacy.official_only;
    delete legacy.official_live_stats;
    apiMocks.getLiveBetaDashboard.mockResolvedValueOnce(legacy);

    renderWithProviders(<LiveBetaDashboardPage />);
    expect(await screen.findByText(/formato precedente/i)).toBeInTheDocument();
    const officialSection = screen.getByRole("heading", { name: "PLAY ufficiali" }).closest("article");
    expect(officialSection).not.toBeNull();
    expect(
      within(officialSection as HTMLElement)
        .getByText("Profitto (unità)")
        .closest("article")
    ).toHaveTextContent("—");
  });
});
