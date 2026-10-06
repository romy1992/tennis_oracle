import { beforeEach, describe, expect, it, vi } from "vitest";
import { screen } from "@testing-library/react";

import { SlipShapeTrialPage } from "./SlipShapeTrialPage";
import type { SlipShapeTrial } from "../types/api";
import { stubDefaultApi } from "../test/mockApi";
import { deferred, renderWithProviders } from "../test/render";

const trial: SlipShapeTrial = {
  window_from: "2026-08-07",
  window_to: "2026-10-05",
  split_date: "2026-09-01",
  model_version: "v4",
  model_name: "voting_ensemble",
  stake: 10,
  min_samples: 30,
  selection_passed: false,
  passing_rules: [],
  conclusion: "Nessuna fascia di quota o di edge resta in ROI positivo sia ad agosto sia a settembre.",
  short_slip_rule: "Due match winner al giorno, i più probabili, senza filtro di quota o di edge.",
  official_slips: {
    label: "Generiche",
    slips_won: 98,
    slips_lost: 377,
    slips_pending: 1,
    slip_win_rate_pct: 20.6,
    picks_won: 1192,
    picks_lost: 650,
    pick_hit_rate_pct: 64.7,
    profit_units: -520.5,
    stake_units: 4750,
    roi_pct: -11
  },
  short_slips: {
    label: "Forma corta",
    slips_won: 19,
    slips_lost: 23,
    slips_pending: 0,
    slip_win_rate_pct: 45.2,
    picks_won: 55,
    picks_lost: 26,
    pick_hit_rate_pct: 67.9,
    profit_units: 12,
    stake_units: 420,
    roi_pct: 2.9
  },
  match_winner_singles: {
    label: "Match winner, singole",
    won: 280,
    lost: 100,
    pending: 0,
    hit_rate_pct: 73.7,
    profit_units: -40,
    stake_units: 3800,
    roi_pct: -1.1
  },
  first_set_singles: {
    label: "Primo set, singole",
    won: 10,
    lost: 10,
    pending: 0,
    hit_rate_pct: 50,
    profit_units: 0,
    stake_units: 200,
    roi_pct: 0
  },
  over_under_singles: {
    label: "Over/under, singole",
    won: 8,
    lost: 12,
    pending: 0,
    hit_rate_pct: 40,
    profit_units: -30,
    stake_units: 200,
    roi_pct: -15
  },
  forward: {
    window_from: "2026-10-06",
    window_to: "2026-10-06",
    ready: false,
    settled_slips: 0,
    slips_needed: 30,
    rule: "quota 1.50-1.80",
    note: "Schedine corte chiuse 0 su 30.",
    short_slips: {
      label: "Forma corta",
      slips_won: 0,
      slips_lost: 0,
      slips_pending: 0,
      slip_win_rate_pct: null,
      picks_won: 0,
      picks_lost: 0,
      pick_hit_rate_pct: null,
      profit_units: 0,
      stake_units: 0,
      roi_pct: null
    }
  },
  checks: [
    {
      method: "raw",
      dimension: "odds",
      band: "1.50-1.80",
      august_settled: 34,
      august_roi_pct: 2,
      september_settled: 24,
      september_roi_pct: -4,
      passed: false
    }
  ]
};

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
  getPublishedLiveStats: vi.fn(),
  getLiveBetaDashboard: vi.fn(),
  getWeeklyBetaReports: vi.fn(),
  getLatestWeeklyBetaReport: vi.fn(),
  getWeeklyBetaReport: vi.fn(),
  generateWeeklyBetaReport: vi.fn(),
  getWalkForwardRuns: vi.fn(),
  getLatestWalkForwardRun: vi.fn(),
  getWalkForwardRun: vi.fn(),
  startWalkForwardRun: vi.fn(),
  getCalibrationRuns: vi.fn(),
  getLatestCalibrationRun: vi.fn(),
  getCalibrationRun: vi.fn(),
  startCalibrationRun: vi.fn(),
  getProbabilityBandAnalysis: vi.fn(),
  getSegmentRoiAnalysis: vi.fn(),
  getSlipShapeTrial: vi.fn()
}));

vi.mock("../services/apiClient", () => ({
  apiClient: apiMocks,
  ApiError: class ApiError extends Error {
    status: number;
    constructor(message: string, status: number) {
      super(message);
      this.status = status;
    }
  }
}));

describe("SlipShapeTrialPage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    stubDefaultApi(apiMocks);
  });

  it("shows the frozen comparison and a failed selection gate", async () => {
    const pending = deferred<SlipShapeTrial>();
    apiMocks.getSlipShapeTrial.mockReturnValue(pending.promise);

    renderWithProviders(<SlipShapeTrialPage />);
    expect(screen.getByText(/Caricamento prova schedine/i)).toBeInTheDocument();

    pending.resolve(trial);
    expect(await screen.findByRole("heading", { name: "Prova schedine" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Selezione invariata" })).toBeInTheDocument();
    expect(screen.getByText(/Nessuna fascia di quota/i)).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Prova dal 6 ottobre" })).toBeInTheDocument();
    expect(screen.getByText(/0 su 30/)).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Forma corta" })).toBeInTheDocument();
    expect(screen.getByText("Quota 1.50-1.80")).toBeInTheDocument();
    expect(screen.getByText("No")).toBeInTheDocument();
    expect(apiMocks.getSlipShapeTrial).toHaveBeenCalledTimes(1);
  });
});
