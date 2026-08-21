import { beforeEach, describe, expect, it, vi } from "vitest";
import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

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

  it("shows loading then fixture rows for the active v4 market", async () => {
    const pending = deferred<ReturnType<typeof makeFixturesPage>>();
    apiMocks.getUpcomingPredictions.mockReturnValue(pending.promise);

    renderWithProviders(<PredictionsPage />);
    expect(screen.getByText("Caricamento partite...")).toBeInTheDocument();

    pending.resolve(makeFixturesPage([makeFixture()]));

    expect(await screen.findByRole("heading", { name: "Partite" })).toBeInTheDocument();
    expect(screen.getByText(/Player A vs/)).toBeInTheDocument();
    expect(screen.queryByLabelText("Versioni modello")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Vincitore partita" })).toHaveClass("active");
  });

  it("highlights a live match with its current score", async () => {
    apiMocks.getUpcomingPredictions.mockResolvedValue(
      makeFixturesPage([
        makeFixture({
          event_status: "Set 2",
          event_live: "1",
          match_lifecycle_status: "started",
          match_lifecycle_label: "In corso",
          live_score: {
            sets: [{ score_first: "6", score_second: "4", score_set: "1" }],
            current_game: "30 - 15",
            status: "Set 2"
          }
        })
      ])
    );

    renderWithProviders(<PredictionsPage />);

    const livePanel = await screen.findByLabelText("Partite in diretta");
    expect(within(livePanel).getByText("LIVE")).toBeInTheDocument();
    expect(within(livePanel).getByText("6-4 · Game 30 - 15")).toBeInTheDocument();
    expect(screen.getAllByText("6-4 · Game 30 - 15")).toHaveLength(2);
  });

  it("shows final score, winner and prediction outcome for a completed match", async () => {
    const base = makeFixture();
    apiMocks.getUpcomingPredictions.mockResolvedValue(
      makeFixturesPage([
        makeFixture({
          event_status: "Finished",
          event_live: "0",
          event_winner: "First Player",
          is_completed: true,
          match_lifecycle_status: "completed",
          match_lifecycle_label: "Conclusa",
          live_score: {
            final_result: "2 - 0",
            sets: [
              { score_first: "6", score_second: "4", score_set: "1" },
              { score_first: "6", score_second: "3", score_set: "2" }
            ],
            status: "Finished"
          },
          prediction: {
            ...base.prediction!,
            actual_winner: "First Player",
            is_correct: true
          }
        })
      ])
    );

    renderWithProviders(<PredictionsPage />);

    const table = await screen.findByRole("table");
    expect(within(table).getByText("FINALE")).toBeInTheDocument();
    expect(within(table).getByText(/2 - 0 · 6-4\s+6-3/)).toBeInTheDocument();
    expect(within(table).getByText(/Vincitore: Player A/)).toBeInTheDocument();
    expect(within(table).getByText("Previsione presa")).toBeInTheDocument();
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

  it("loads predictions for the active v4 model", async () => {
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
    expect(versions.every((v) => v === "v4")).toBe(true);
    expect(new Set(names)).toEqual(new Set(["voting_ensemble"]));
  });

  it("renders first-set fallbacks and over/under value metrics in their market tabs", async () => {
    const user = userEvent.setup();
    apiMocks.getUpcomingPredictions.mockResolvedValue(
      makeFixturesPage([
        makeFixture({
          extra_markets: [
            {
              market: "first_set_winner",
              model_version: "first_set_winner_v2",
              model_name: "random_forest",
              selection: "Second Player",
              probability: 0.64,
              odds: 1.9,
              void_odds: 1.5625,
              edge: 21.6,
              published_at: "2026-07-21T09:00:00Z"
            },
            {
              market: "over_under_games",
              model_version: "over_under_games_v1",
              model_name: "random_forest",
              selection: "Over 20.5",
              probability: 0.6,
              odds: 1.8,
              void_odds: 1.6667,
              edge: 8,
              published_at: "2026-07-21T09:00:00Z"
            }
          ]
        })
      ])
    );

    renderWithProviders(<PredictionsPage />);
    await screen.findByRole("heading", { name: "Partite" });

    await user.click(screen.getByRole("button", { name: "Vincitore 1° set" }));
    expect(screen.getByText(/Pagina: PLAY 1 · BORDERLINE 0 · NO BET 0 · senza quota 0/)).toBeInTheDocument();
    let cells = within(screen.getByRole("table")).getAllByRole("cell");
    expect(cells[5]).toHaveTextContent("Player B");
    expect(cells[6]).toHaveTextContent("64%");
    expect(cells[7]).toHaveTextContent("1,90");
    expect(cells[8]).toHaveTextContent("1,56");
    expect(cells[9]).toHaveTextContent("+21,6%");
    expect(cells[11]).toHaveTextContent("PLAY");

    await user.click(screen.getByRole("button", { name: "Over/Under Games" }));
    cells = within(screen.getByRole("table")).getAllByRole("cell");
    expect(cells[5]).toHaveTextContent("Over 20.5");
    expect(cells[7]).toHaveTextContent("1,80");
    expect(cells[8]).toHaveTextContent("1,67");
    expect(cells[9]).toHaveTextContent("+8%");
    expect(cells[10]).toHaveTextContent("+8%");
    expect(cells[11]).toHaveTextContent("PLAY");
    expect(screen.getByText(/Pagina: PLAY 1 · BORDERLINE 0 · NO BET 0/)).toBeInTheDocument();
  });

  it("does not reuse match-winner outcome filters or result legend on extra markets", async () => {
    const user = userEvent.setup();
    renderWithProviders(<PredictionsPage />);
    await screen.findByRole("heading", { name: "Partite" });

    await user.click(screen.getByRole("button", { name: "Giocate" }));
    expect(await screen.findByLabelText("Filtro esito previsione")).toBeInTheDocument();
    expect(document.querySelector(".result-legend")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Vincitore 1° set" }));
    expect(screen.queryByLabelText("Filtro esito previsione")).not.toBeInTheDocument();
    expect(document.querySelector(".result-legend")).not.toBeInTheDocument();
    await waitFor(() => {
      expect(apiMocks.getUpcomingPredictions).toHaveBeenLastCalledWith(
        expect.objectContaining({ status: "played", outcome: undefined })
      );
    });
  });
});
