import { beforeEach, describe, expect, it, vi } from "vitest";
import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { BettingSlipsPage } from "./BettingSlipsPage";
import { ApiError } from "../services/apiClient";
import { makeCalendar, makeDailySlips, makeSlip } from "../test/fixtures";
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
  downloadBettingSlipImage: vi.fn(),
  downloadBettingSlipImagesZip: vi.fn(),
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

describe("BettingSlipsPage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    stubDefaultApi(apiMocks);
  });

  it("shows loading then v4 daily slips without technical model selectors", async () => {
    const pending = deferred<ReturnType<typeof makeCalendar>>();
    apiMocks.getBettingSlipCalendar.mockReturnValue(pending.promise);

    renderWithProviders(<BettingSlipsPage />);
    expect(screen.getByText("Caricamento schedine...")).toBeInTheDocument();

    pending.resolve(makeCalendar());

    expect(await screen.findByRole("heading", { name: "Consiglio schedina" })).toBeInTheDocument();
    expect(await screen.findByText("Play facile")).toBeInTheDocument();
    expect(screen.queryByLabelText("Versioni modello")).not.toBeInTheDocument();
    expect(screen.queryByLabelText("Modelli")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "voting_ensemble" })).not.toBeInTheDocument();
    expect(screen.getByTestId("slip-market-models")).toHaveTextContent(
      "Match Winner v4 / voting_ensemble · Primo set first_set_winner_v2 / logistic_regression · Over/Under over_under_games_v1 / random_forest"
    );
  });

  it("renders two markets from the same event as distinct picks", async () => {
    const slip = makeSlip();
    const matchWinnerPick = slip.picks[0];
    const overUnderPick = {
      ...matchWinnerPick,
      market: "over_under_games",
      predicted_winner: "Over 20.5",
      predicted_winner_label: "Over 20.5 games"
    };
    const mixedDaily = {
      ...makeDailySlips(),
      slips: [
        makeSlip({
          picks: [matchWinnerPick, overUnderPick],
          pick_count: 2,
          picks_total: 2,
          picks_pending: 2
        })
      ]
    };
    apiMocks.getDailyBettingSlips.mockResolvedValue(mixedDaily);
    apiMocks.regenerateDailyBettingSlips.mockResolvedValue(mixedDaily);

    renderWithProviders(<BettingSlipsPage />);

    const table = await screen.findByRole("table");
    const rows = within(table).getAllByRole("row");
    expect(rows).toHaveLength(3);
    expect(within(table).getByText("Vincitore partita")).toBeInTheDocument();
    expect(within(table).getByText("Over/Under Games")).toBeInTheDocument();
    expect(within(table).getByText("Player A")).toBeInTheDocument();
    expect(within(table).getByText("Over 20.5 games")).toBeInTheDocument();
  });

  it("filters persisted slips through the four strategy sub-tabs", async () => {
    const daily = {
      ...makeDailySlips(),
      slips: [
        makeSlip({ label: "Generica attuale", strategy_family: "generic" }),
        makeSlip({
          id: "experimental-play",
          slip_key: "experiment_play_only_3",
          label: "Solo PLAY test",
          strategy_family: "play_only",
          strategy_version: "play_only_v1",
          is_experimental: true
        })
      ]
    };
    apiMocks.getDailyBettingSlips.mockResolvedValue(daily);
    apiMocks.regenerateDailyBettingSlips.mockResolvedValue(daily);

    const user = userEvent.setup();
    renderWithProviders(<BettingSlipsPage />);

    expect(await screen.findByText("Generica attuale")).toBeInTheDocument();
    const strategyTabs = screen.getByLabelText("Strategia consiglio");
    expect(within(strategyTabs).getAllByRole("button")).toHaveLength(4);

    await user.click(within(strategyTabs).getByRole("button", { name: "Solo PLAY" }));
    expect(await screen.findByText("Solo PLAY test")).toBeInTheDocument();
    expect(screen.queryByText("Generica attuale")).not.toBeInTheDocument();
    expect(
      screen.getByText(/Risultati sperimentali: non pubblicati come consiglio ufficiale/)
    ).toBeInTheDocument();
  });

  it("shows a prominent live section and score for picks in progress", async () => {
    const slip = makeSlip();
    const livePick = {
      ...slip.picks[0],
      event_status: "Set 2",
      match_lifecycle_status: "started",
      match_lifecycle_label: "In corso",
      live_score: {
        sets: [{ score_first: "6", score_second: "4", score_set: "1" }],
        current_game: "30 - 15",
        status: "Set 2"
      }
    };
    apiMocks.getDailyBettingSlips.mockResolvedValue({
      ...makeDailySlips(),
      slips: [makeSlip({ picks: [livePick] })]
    });

    renderWithProviders(<BettingSlipsPage />);

    const livePanel = await screen.findByLabelText("Partite in diretta");
    expect(within(livePanel).getByText("LIVE")).toBeInTheDocument();
    expect(within(livePanel).getByText("6-4 · Game 30 - 15")).toBeInTheDocument();
    expect(screen.getAllByText("6-4 · Game 30 - 15")).toHaveLength(2);
  });

  it("keeps the final score and explicit pick outcome after completion", async () => {
    const slip = makeSlip();
    const completedPick = {
      ...slip.picks[0],
      pick_status: "won" as const,
      actual_winner_label: "Player A",
      is_correct: true,
      event_status: "Finished",
      match_lifecycle_status: "completed",
      match_lifecycle_label: "Conclusa",
      live_score: {
        final_result: "2 - 0",
        sets: [
          { score_first: "6", score_second: "4", score_set: "1" },
          { score_first: "6", score_second: "3", score_set: "2" }
        ],
        status: "Finished"
      }
    };
    const completedDaily = {
      ...makeDailySlips(),
      slips: [
        makeSlip({
          picks: [completedPick],
          slip_status: "won",
          picks_pending: 0,
          picks_won: 1
        })
      ]
    };
    apiMocks.getDailyBettingSlips.mockResolvedValue(completedDaily);
    apiMocks.regenerateDailyBettingSlips.mockResolvedValue(completedDaily);

    renderWithProviders(<BettingSlipsPage />);

    const table = await screen.findByRole("table");
    expect(within(table).getByText("FINALE")).toBeInTheDocument();
    expect(within(table).getByText(/2 - 0 · 6-4\s+6-3/)).toBeInTheDocument();
    expect(within(table).getByText(/Esito reale: Player A/)).toBeInTheDocument();
    expect(within(table).getByText(/Pick vinta/)).toBeInTheDocument();
    expect(within(table).getByText("Presa")).toBeInTheDocument();
  });

  it("shows empty state when the day has no slips", async () => {
    apiMocks.getDailyBettingSlips.mockResolvedValue({
      ...makeDailySlips(),
      slips: []
    });

    renderWithProviders(<BettingSlipsPage />);

    expect(
      await screen.findByText("Nessuna schedina disponibile · Generiche")
    ).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Scarica immagini" })).toBeDisabled();
  });

  it("downloads a single slip image and the zip of all slips", async () => {
    const createObjectURL = vi.fn(() => "blob:slip-image");
    const revokeObjectURL = vi.fn();
    Object.defineProperty(window.URL, "createObjectURL", {
      configurable: true,
      value: createObjectURL
    });
    Object.defineProperty(window.URL, "revokeObjectURL", {
      configurable: true,
      value: revokeObjectURL
    });
    const clickSpy = vi
      .spyOn(HTMLAnchorElement.prototype, "click")
      .mockImplementation(() => undefined);

    apiMocks.downloadBettingSlipImage.mockResolvedValue({
      blob: new Blob(["png"], { type: "image/png" }),
      filename: "safe.png"
    });
    apiMocks.downloadBettingSlipImagesZip.mockResolvedValue({
      blob: new Blob(["zip"], { type: "application/zip" }),
      filename: "schedine.zip"
    });

    const user = userEvent.setup();
    renderWithProviders(<BettingSlipsPage />);

    expect(await screen.findByText("Play facile")).toBeInTheDocument();

    await user.click(screen.getAllByRole("button", { name: "Scarica immagine" })[0]);
    expect(apiMocks.downloadBettingSlipImage).toHaveBeenCalledWith(
      expect.objectContaining({ slip_key: "play_easy" })
    );
    expect(await screen.findByText("Immagine schedina play_easy scaricata.")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Scarica immagini" }));
    expect(apiMocks.downloadBettingSlipImagesZip).toHaveBeenCalled();
    expect(await screen.findByText("Immagini di tutte le schedine scaricate.")).toBeInTheDocument();
    expect(createObjectURL).toHaveBeenCalled();
    expect(clickSpy).toHaveBeenCalled();

    clickSpy.mockRestore();
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
          version: "v4",
          models: [
            {
              model: "voting_ensemble",
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
