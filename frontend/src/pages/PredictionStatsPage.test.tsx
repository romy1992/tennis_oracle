import { beforeEach, describe, expect, it, vi } from "vitest";
import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { PredictionStatsPage } from "./PredictionStatsPage";
import type { DailyPredictionStatsDay } from "../types/api";
import { stubDefaultApi } from "../test/mockApi";
import { renderWithProviders } from "../test/render";
import { formatDate } from "../utils/tennis";

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

function makeDay(date: string, total: number): DailyPredictionStatsDay {
  return {
    day_offset: 0,
    date,
    predictions_total: total,
    predictions_resolved: total,
    predictions_correct: 1,
    predictions_lost: 0,
    accuracy_pct: 100,
    pending: 0,
    predictions_with_odds: total,
    avg_predicted_winner_odds: 1.5,
    avg_winning_odds: 1.5,
    theoretical_profit_units: 0.5,
    theoretical_roi_pct: 10
  };
}

const shuffledDays: DailyPredictionStatsDay[] = [
  makeDay("2026-09-01", 1),
  makeDay("2026-09-07", 7),
  makeDay("2026-09-03", 3),
  makeDay("2026-09-08", 0),
  makeDay("2026-09-05", 5),
  makeDay("2026-09-02", 2),
  makeDay("2026-09-06", 6),
  makeDay("2026-09-04", 4)
];

describe("PredictionStatsPage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    stubDefaultApi(apiMocks);
    apiMocks.getDailyPredictionStats.mockResolvedValue({
      model_version: "v4",
      days: shuffledDays
    });
  });

  it("shows the newest five days first and paginates older ones", async () => {
    const user = userEvent.setup();
    renderWithProviders(<PredictionStatsPage />);

    expect(await screen.findByRole("heading", { name: "Andamento per giorno" })).toBeInTheDocument();
    expect(screen.getByText("5 giorni · dalla più recente")).toBeInTheDocument();

    const rows = screen.getAllByRole("row").slice(1);
    expect(rows).toHaveLength(5);
    expect(within(rows[0]).getByText(formatDate("2026-09-07"))).toBeInTheDocument();
    expect(within(rows[1]).getByText(formatDate("2026-09-06"))).toBeInTheDocument();
    expect(within(rows[2]).getByText(formatDate("2026-09-05"))).toBeInTheDocument();
    expect(within(rows[3]).getByText(formatDate("2026-09-04"))).toBeInTheDocument();
    expect(within(rows[4]).getByText(formatDate("2026-09-03"))).toBeInTheDocument();
    expect(screen.queryByText(formatDate("2026-09-02"))).not.toBeInTheDocument();
    expect(screen.queryByText(formatDate("2026-09-08"))).not.toBeInTheDocument();
    expect(screen.getByText(/1\/2/)).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Giorni precedenti" }));

    const olderRows = screen.getAllByRole("row").slice(1);
    expect(olderRows).toHaveLength(2);
    expect(within(olderRows[0]).getByText(formatDate("2026-09-02"))).toBeInTheDocument();
    expect(within(olderRows[1]).getByText(formatDate("2026-09-01"))).toBeInTheDocument();
    expect(screen.queryByText(formatDate("2026-09-07"))).not.toBeInTheDocument();
    expect(screen.getByText(/2\/2/)).toBeInTheDocument();
  });
});
